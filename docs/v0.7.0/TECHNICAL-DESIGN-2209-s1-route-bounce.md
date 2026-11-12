# TECHNICAL DESIGN — #2209 slice S1, split into S1a (route + bounce core) and S1b (holds, disputes, merge guard)

**Status:** DRAFT, round 3 (round 2 wording changes R2-1 to R2-4 applied, tagged **[AR2-n]**). Architect round 1 (`.claudetmp/design/architect-2209-s1-2026-10-31T060000Z.md`)
returned CHANGES_REQUIRED with C1-C9. This revision folds them in, and each change is tagged
**[AR1-Cn]**. §9 records every round-1 ruling. Coding of S1a may start only after the architect approves
this revision.
**Author:** `technical-design` (autonomous worker cycle; no human present)
**Date:** 2026-10-31
**Issue:** #2209 (milestone v0.7.0). **Risk tier: HIGH.** `scripts/automation/lib/merge_authority.py`
and `bootstrap/**` are protected surfaces, so the CODEOWNER gate applies at merge.
**Binding inputs:**
- `docs/v0.7.0/REQUIREMENTS-2209-overseer-rejections-to-worker.md` (REQ-1 to REQ-14, ESC-1 to ESC-3);
- `docs/v0.7.0/ADR-2209-overseer-rejections-to-worker.md` revision 11 (AD-1 to AD-7, §4 Slices, §5);
- the PR #2223 review carry list (security, risk-assessor, code review), restated in §8.

**Tree read at:** `96d7ae66f` (branch `worker-2209-s1-route-bounce-261031042001-2375947`). #2174 is
merged (PR #2225), so the ADR's "S1 → #2174 → S2" ordering constraint is already met on the #2174 side.

> This document specifies contracts, not code. A "must" is a requirement on the implementation.
> Choices the inputs left open are labelled **TD-D<n>**, each with its reason.

---

## 0. Search-first findings and verified state

**Searched:** `scripts/automation/lib/merge_authority.py`, `merge_authority_cli.py`, `bootstrap/merge_authority.sh`,
`scripts/automation/lib/{correlation,github,merge_config}.py`, `scripts/oversight/codeowners.py`,
`scripts/oversight/lib/audit_log.py`, `scripts/framework/{requester_trust,require_human_approval}.py`,
`scripts/automation/pr_review_cli.py`, `bin/hos-cron`, `bootstrap/create_branch.sh`,
`tests/automation/test_{bounce_gate,merge_authority_cli,pr_review_resolution}.py`,
`tests/framework/test_requester_trust.py`, `contract/OVERSIGHT-CONTRACT.md:440-470`,
`.claude/agents/overseer.md:300-353,495-535`, and the Overseer clone's audit records for PR #2207.

| # | Verified fact | Where |
|---|---|---|
| F1 | `bounce_count(cid, *, repo_root)` counts every `pr-bounced` event for the cid, for all time. `test_t2_8` monkeypatches it with the exact signature `(cid, *, repo_root)`, so the CLI's `bounce-count` call must keep that call shape. | `merge_authority.py:1177`; `test_merge_authority_cli.py:447-462` |
| F2 | `record_pr_bounce` has no head guard and writes no `head_sha` (ADR AF-2). Its only callers are the overseer's improvised Python (`overseer.md:334,349`) and tests. No code in `bin/`, `bootstrap/` or `scripts/` calls it, `_bounce_comment_body` or `_BOUNCE_REASON_CATEGORIES`. | grep |
| F3 | No test or script depends on the current bounce comment's wording. `bin/hos-cron:1289-1295` detects a bounce from draft + `needs-ai`, not from the text. Tests assert only `**Reason category:**`, `**Summary:**` and the failure token. | `test_bounce_gate.py:258-261` |
| F4 | `derive_cid` (a 12-hex hash) has no production caller. ADR-2209's `bounce_cid` is a different form (`issue-<N>`). `correlation.py` is not edited. | `correlation.py:69` |
| F5 | Step 6 resolves the reviewer with `codeowners.resolve_human_reviewer`. It reads the **working-tree** file, uses last-match-wins per path, takes the first user owner over the sorted changed files, and falls back to `HUMAN_REVIEWER` when only team, bot or e-mail owners match. `requester_trust.codeowners_humans` is a different function: the set of every individual named anywhere in the file. **The two disagree on team-owned and partly owned paths.** | `codeowners.py:284-375`; `requester_trust.py:263-282` |
| F6 | `github._run_gh` returns `None` on 404 and on an empty body. It raises `RateLimitError` on any 403 or 429 after retries, and `GitHubError` on 5xx, timeouts and other 4xx. | `github.py:123-272` |
| F7 | `list_pull_files` paginates `pulls/{n}/files` (GitHub caps it at 3,000 files). The PR object carries `changed_files`, which can be cross-checked against the list length. There is no compare, contents, issue-events or check-suite helper in `github.py`. `GitHubError` carries `status_code` (`None` for a timeout or network failure), and `RateLimitError` subclasses it. | `github.py:20-30,496-523` |
| F8 | `detect_human_hold_directive` decides whether a newer head superseded a hold by comparing against the head's **committer date**, which the pusher controls. A future-dated commit makes a hold posted on that same head look superseded. This is the security carry item "commit dates can be forged". | `merge_authority.py:120-164`; `merge_authority_cli.py:516-530` |
| F9 | `audit_log.read_stream` yields nothing for an absent `audit/log/` and raises `ValueError` on a malformed record. | `audit_log.py:160-187` |
| F10 | The CLI's T1.7 test requires every subcommand to reject `--head-sha`, `--force`, `--config`, `--manifest` and `--repo-root` (TD-1357 §3.4.0 Rule A). T4.7 asserts that no read-only subcommand exits 3. | `test_merge_authority_cli.py:212-231,650-653` |
| F11 | `hypothesis` is not installed in either interpreter. The property test must use stdlib exhaustive enumeration. | `import hypothesis` fails |
| F12 | **PR #2207 at 02:27Z.** Head `d33c93ba7c79d12c184ee1eb8c32b4b6916a2768`, parent and merge base `a05c7e363ba7fd68ff9be6620c8b120a6bf8fc3a`. Changed files: `bin/hos-cron` (M), `docs/CRON-SETUP.md` (M), `prompts/bin/hos-cron.v2171.md` (A), `tests/automation/test_hos_cron.py` (M). The Overseer clone's record `2026-10-29T022742Z-human-required-dd40aafac48b.json` has `decision: HUMAN_REQUIRED`, `reason_category: GATE_UNSATISFIED`, `tier: HIGH`, and a summary naming "new shellcheck SC1090 at bin/hos-cron:1039". The PR is for #2171 slice 1 (squash-merged later as `ca60bc877`). | `git show d33c93ba7`; `../Overseer/audit/log/2026/10/` |

**Reused rather than rebuilt:** `check_register_completeness`, `check_required_content_checks`,
`detect_human_hold_directive`, `record_pr_bounce`'s halt ordering, `_convert_pr_to_draft`,
`audit_log.{read_stream,write_event}`, `codeowners.{parse_codeowners,get_owners_for_path}` and its
classification helpers (loaded by path, the same idiom as `merge_authority_cli._load_codeowners_module`),
`require_human_approval.is_bot_reviewer`, `merge_config.resolve_config`, and the CLI's envelope and
`_Outcome` plumbing.

---

## 1. The split and the landing order

ADR §4's S1 is 14 files, and every PR #2223 review advised splitting it. The rulings still open
(ESC-3, ARCH-ESC-1, ARCH-ESC-2 and the proposed ESC-4, treated here as **unruled**) gate S1's merge,
not its build. This document splits S1 along the line those rulings draw:

- **S1a (this cycle):** everything that no open ruling changes except ESC-3 and ARCH-ESC-1, and those
  two are each isolated behind a single named branch or constant (§7).
- **S1b (a later cycle):** everything ESC-4 or ARCH-ESC-2 can change. §6 names its files, rulings and
  obligations.

**Landing order (binding): S1a → S1b → S2 → S3.** S2 is the only caller of `route`. It must not land
before S1b, because S1b supplies the inputs S1a stubs (path blocks, disputes, the veto window) and the
`route-proceed` and `merge-guard` pair that is the only way to a merge (AD-5).

**S1a is inert, with three exceptions.** Nothing calls `route` or `bounce` until S2. S1a's `route` also
**cannot return `PROCEED` from the CLI** (TD-D4), so even a premature caller could not merge on it.
The live effects, all of which the ADR's "S1's live effects" requires, are:
1. the bounce comment switches to the AD-4 legacy rendering for today's `failures=` callers;
2. `record_pr_bounce` resolves and records `head_sha`, and skips a repeated bounce on the same head
   (TD-D5);
3. `bounce_count` gains an optional window. Its default is all-time, so the `bounce-count` CLI and
   today's callers see no change. With today's `pr-<n>` keys and no `human-required` record carrying a
   `trigger`, the window would make no difference anyway.

---

## 2. Decisions

### TD-D1. The findings file carries structured parts. The CLI alone builds `key`.

ADR AD-1 says the key is "canonicalized by the CLI". Parsing a caller-built string such as
`check:<run>:<rule>:<path>` is ambiguous when a check-run name or path contains `:`. The findings file
therefore carries the parts (`check_run`, `rule`, `path`, `slug`), and a `key` field in the file is
refused as an unknown key. **The CLI builds every key.** That is the strongest form of
canonicalization, and it removes a parse step. The resulting key strings are exactly the ADR's formats.

### TD-D2. Same-head identity depends on the class (refines rule 6(c) and R-7)

**Approved, architect round 1.** Cite this as: "ADR-2209 AD-5 slug-stability, refined for CHECK by
TD-D2 (architect round 1)".

Rule 6(c) compares an LLM key on an already-bounced head by class and path, so a reworded slug cannot
manufacture a new bounce. The identity tuple is:

| Origin and class | Identity | Reason |
|---|---|---|
| code-collected (`PROCEDURAL`, `REQUIRED_CHECK`, size `SCOPE`) | `(class, key)` | Deterministic, with no slug to drift |
| LLM `CHECK` | `("CHECK", check_run, path)` | `check_run` is validated against the head's real check runs, so it cannot be invented. `rule` is LLM-transcribed and is excluded |
| LLM `MERITS`, `REVIEW_FINDING`, `SCOPE` | `(class, path or "-")` | ADR slug-stability rule, unchanged |

For `CHECK`, this is finer than the ADR's class+path rule. Two different check runs on one path are two
findings. The LLM still cannot inflate bounces, because the set of check runs is bounded and real.
Residual R-7 (delay) remains for the other classes. The withdraw half of R-7 belongs to S1b (§6.3).

### TD-D3. Reviewer resolution uses step 6's algorithm on base-ref text. The ADR's humans-set parser is kept as a drift guard.

The risk-assessor's carry item requires CODEOWNERS teams to resolve the same way step 6 does. F5 shows
that `requester_trust.codeowners_humans`'s rules (ADR AD-5a) do not. S1a therefore:
- fetches the CODEOWNERS text at the PR's **base SHA** (AF-7), trying the same three locations, in the
  same order, as `codeowners.load_codeowners`;
- resolves the login by calling `codeowners.parse_codeowners` and `get_owners_for_path` and repeating
  `resolve_human_reviewer`'s classification order on that text. A parity test (T-CO-2) pins the two
  against each other on the `test_pr_review_resolution.py` cases;
- keeps `_codeowners_humans_from_text` as ADR AD-5a names it, with the same output as
  `requester_trust.codeowners_humans` (T-CO-1). It serves as a runtime drift guard: when the resolution
  source is `codeowners`, the resolved login must be in that set. Otherwise `route` exits 1 with
  `codeowners_resolution_drift`.

No new parser file is added (ADR: "S1 adds no file for it"). `tests/framework/test_requester_trust.py`'s
no-second-parser guard scans `scripts/framework/` only, so it is not affected.

**Approved, architect round 1, as an amendment to ADR-2209 AD-5a; wording confirmed in round 2
[AR2-1].** The architect's verbatim text:

> *ADR-2209 AD-5a amendment (architect, TD-2209 round 1, wording confirmed round 2, 2026-10-31): the reviewer is resolved by `codeowners.resolve_human_reviewer`'s algorithm (last-match-wins per path, first user owner over sorted changed files, team/bot/e-mail-only → `HUMAN_REVIEWER`) applied to CODEOWNERS text read at the PR's base SHA, trying `.github/CODEOWNERS`, `CODEOWNERS`, `docs/CODEOWNERS` in that order. `_codeowners_humans_from_text` (byte-equivalent to `requester_trust.codeowners_humans`) is retained as a fail-closed consistency check, not as the resolver: a `codeowners`-sourced login absent from that set is exit 1, `codeowners_resolution_drift`, `error_class: deterministic`.*

### TD-D4. S1a's `route` cannot return `PROCEED` from the CLI

AD-5's code-collected set includes the validator artifact (AF-5). That collector needs the git
ancestry checks in `overseer.md:300-324`, and it is shared with `merge-guard`, so it lands in S1b. Until
then `route` reports `collectors_complete = false`, and rule 8 (and rule 2's approval branch) returns
`HOLD` with reason `collectors-incomplete`, never `PROCEED`. This fails closed by construction: even if S2
landed early, nothing could merge on an S1a `route`. S1b flips the flag when it adds the collector.

### TD-D5. `record_pr_bounce` resolves the head itself when no caller supplies it

The ADR lists "`record_pr_bounce` writes `head_sha` and skips a repeated bounce on the same head" as a
live S1 effect. Today's callers are improvised Python that will not pass a new argument. So when
`head_sha` is `None`, `record_pr_bounce` reads `GET /pulls/{n}` once, **before** posting anything. A
failed read, or a missing `head.sha`, raises `GitHubError`, and nothing is posted (the halt direction).
Callers that pass `head_sha` (both new CLI subcommands) skip the read.

**Residual R-TD5 (head race) [AR1-C8].** An improvised caller computes its failures on head H1. If the
worker pushes H2 before `record_pr_bounce` reads the head, the comment and the event name H2 while
listing H1's failures. The direction is safe. Nothing merges on a bounce. On H2's next cycle the
findings are either:
- the same keys, so the cycle skips, and the worker has already been told about exactly those findings;
- new keys, so the cycle bounces;
- none, so no bounce happens.

The worst case is one comment whose head label is newer than the head it was computed on. The race
disappears for 4a and 4c once S2 moves them onto `route` and `bounce`, which pin the head (§3.12).

### TD-D6. The #902 check in `route` uses a server-bounded head time, not the committer date alone

F8 is live today: a future-dated commit lets a hold posted on that very head look superseded. The
non-sticky #902 check in rule 1 is in S1a, so S1a fixes it **for `route` only**. The function
`effective_head_time` (§3.10) caps the committer date at the **`created_at` of the `github-actions`
check suite for the head SHA [AR1-C7, option (a)]**. GitHub creates that suite server-side when the
push event is processed, before any run in it is queued or started. A run that is still queued, with
`started_at: null`, therefore does not leave the bound open. With no `github-actions` suite on the head,
the result is `None`, so every matching directive counts (the library's existing fail-safe), which gives
`LEGACY`. Option (a) is chosen, so residual R-TD6 (queue latency widening the window) does not arise.
The remaining window is the push-to-suite-creation delay, which is server-side and typically seconds.

**Approved, architect round 1 (with C7).** The `hold-directive` subcommand and the matrix keep today's
behaviour (REQUIREMENTS §3 puts #902 out of scope). Per the Q3 ruling, the same flaw in them goes to a
**separate follow-up issue, which the worker files**; it is not widened into S1a (§11). S1b's
sticky-hold "held head" must use this primitive, never timeline `committed` dates (§6.3).

### TD-D7. `route` and `bounce` take `--step`, a subject selector

`check_register_completeness` needs the step, and AD-5 has the CLI collect code findings itself. The
step is a **subject** selector under TD-1357 Rule A, the same as `register --step`, and it is echoed in
the record. The manifest path stays derived. ADR AD-5a's "the overseer passes only `--pr` and
`--findings-file`" concerns the AD-5a review and label inputs, which `route` still fetches itself.

### TD-D8. `route` and `bounce` are overseer-only mutation subcommands

Both subcommands write: a comment, an audit event, a label and the draft state. They accept only
`--app overseer`; any other value is a usage error (exit 2). Before any write they require
`HOS_BOT_LOGIN` (exported by `get_app_token.sh`) to equal `config.overseer_handle`, compared
case-insensitively. Otherwise they exit 1 with `acting_identity_not_overseer`. This mirrors
`pr_review_cli.py:382-401,542`.

### TD-D9. A same-head skip repairs an unfinished finalize, and never re-bounces

`record_pr_bounce`'s finalize steps (label, then draft) are best-effort, and with the same-head skip a
failed label would otherwise never be retried. That is the #2207 silent-stall class. On a skip, the
PR's current state is read and handled deterministically:

| PR state on the skipped head | Action |
|---|---|
| draft, `needs-ai` present | none |
| draft, `needs-ai` absent | add `needs-ai` (the label failed earlier), **unless** an `unlabeled` `needs-ai` event by any actor exists after `T`, which is deliberate, so do nothing [codex second review, CWE-841] |
| not draft, `needs-ai` present | convert to draft (the draft step failed earlier), **unless** a `ready_for_review` event by any actor exists after `T`, which is deliberate, so do nothing [codex second review, CWE-841] |
| not draft, `needs-ai` absent, **and** a `ready_for_review` event or an `unlabeled` `needs-ai` event exists after `T` | none. The state is deliberate (for example S3 option (a), or a human override), so REQ-12 applies |
| not draft, `needs-ai` absent, and **no** such event after `T` | add `needs-ai`, then convert to draft. **Both finalize steps failed** after the audit event was written, for example because the token expired [codex second review, CWE-703] |

**Disambiguating the last two rows [codex second review].**
- **Where `T` comes from.** `T` is the `comment_created_at` of the latest `pr-bounced` event for
  `(cid, head_sha)`. A legacy event without that field uses its `timestamp` instead.
  **Residual R-TD9 (clock skew):** that fallback `timestamp` comes from the overseer's local clock, not
  GitHub's. Skew can therefore misread a deliberate ready-marking or label removal made just after the
  bounce as "before `T`", and the repair would undo it. Only pre-S1a events are exposed: every event
  S1a writes carries `comment_created_at`.
- **R-TD9b — RESOLVED in S1a (codex second review, CWE-841).** It was raised by the security delta
  review of be2f3c69f (SHOULD_FIX low). The single-missing states used to undo a deliberate human act:
  a ready-marking that left the label on was re-drafted, and a deliberate label removal on a draft was
  re-labelled. Both states now check the events after `T` first, as in the table above.
- **The evidence.** It is read server-side, from `github.list_issue_events(owner, repo, pr, max_pages=_ISSUE_EVENTS_MAX_PAGES)`.
- **The actor rule.** An event by **any** actor counts as deliberate. A human's or the human-proxy's
  ready-marking or label removal is an override as deliberate as the worker's, and the repair must not
  undo it.
- **When the read fails.** The read is needed for every state except "draft, `needs-ai` present". If
  it fails or is truncated, the repair **raises before any write**, with no guess either way. The CLI then exits 1 per §3.16 (`github_read_failed`
  classified by `classify_github_error`, or `issue_events_truncated`, deterministic).

The table is implemented once, as `repair_bounce_finalize(owner, repo, pr_number, *, cid, head_sha, repo_root) -> list[str]`
in `merge_authority.py`. It returns the repairs made. Its callers are `record_pr_bounce`'s same-head
skip (§3.6 step 3) and `route` on a `NOOP` that carries the action `repair-finalize` (§3.8 rule 6c,
§3.13 step 15). That second caller exists because a route-driven cycle on an already-bounced head ends
in rule 6c and never reaches `record_pr_bounce`. A label or draft **write** failure during the repair is
still best-effort: it goes into `finalize_errors`, and it is retried next cycle.

No comment is posted, no event is written and no budget is spent. The payload reports
`finalize_repaired: [...]`.

### TD-D10. Rule 2's `PROCEED` also requires every blocker to be absent (stricter than the ADR)

ADR AD-5a says that on an escalated head "no later rule applies". The carry-list property says there is
no `PROCEED` while any hold, veto window or open code finding applies. To satisfy both, rule 2's
approval branch returns `HOLD_VETO` while a veto window is open or due to start, and `HOLD` while a
`path_pending_escalation` block applies. This moves only in the delay direction.

**Approved, architect round 1, with C1 and C2:**
- **[AR1-C1] No stall on an unstarted window.** Rule 2 returns before rule 4, so without care a
  `NEEDS_START` window would never be started on an escalated head, and the PR would sit in `HOLD_VETO`
  forever. Every rule-2 result therefore carries `actions=("start-veto-window",)` when
  `veto == NEEDS_START`. The approval branch returns `HOLD_VETO` **with** that action when the veto is
  `NEEDS_START`, and `HOLD_VETO` with **no** action when it is `OPEN`. Property P7 (§5.1) pins this.
- **[AR1-C2] An escalation never blocks its own PR.** `RouteInputs` gains `pr: int`. `route_pr` ignores
  a `PATH_PENDING_ESCALATION` block whose `source_pr == pr`, because the PR's own escalation is handled
  by rule 2, and blocking on it would deadlock the approval that resolves it. A `PATH_HOLD` or
  `UNKNOWN_SCOPE` block from the same PR **still applies** (rule 1), because a hold on P is released on
  P (ADR AD-2).

---

## 3. Contracts (S1a)

All new routing code goes in `scripts/automation/lib/merge_authority.py`, after the existing bounce
section, under a banner `# Rejection routing (#2209 S1a)`. **[AR1-C5]** The three new generic GitHub
reads go in `scripts/automation/lib/github.py` (§3.17). **All edits in both files are additive.** No
existing public name changes signature incompatibly. The changes to existing functions are new
keyword-only parameters with defaults (§3.5, §3.6).

### 3.1 Constants

| Name | Value | Note |
|---|---|---|
| `BOUNCE_CAP` | `2` (unchanged) | REQUIREMENTS §3 |
| `EPOCH_RESETS_AT_ESCALATION` | `True` | **ARCH-ESC-1 (A).** Setting it to `False` is the whole of option (B). Its comment must say so and cite ARCH-ESC-1 |
| `FINDING_CLASSES` | `("PROCEDURAL","REQUIRED_CHECK","CHECK","MERITS","SCOPE","REVIEW_FINDING","REVIEW_CHAIN")` | AD-1; `REVIEW_CHAIN` added by #2346 |
| `LLM_FINDING_CLASSES` | `frozenset({"CHECK","MERITS","SCOPE","REVIEW_FINDING","REVIEW_CHAIN"})` | The classes a findings file may use. `REVIEW_CHAIN` (#2346) is an incomplete review chain: key `REVIEW_CHAIN:-:<role>`, `slug` one of `REVIEW_CHAIN_ROLES`, no `path`; derives `REGISTER_GAP`; the bounce summary begins `incomplete-review-chain:` and lists the roles |
| `ESCALATION_TRIGGERS` | `("upheld-dispute","bounce-cap","reviewer-conflict","decision")` | AD-6 |
| `_BOUNCE_REASON_CATEGORIES` | the existing four plus `CHECK_FAILURE`, `MERITS_FINDING`, `SCOPE_SIZE`, `REVIEW_FINDING`, `MIXED` | AD-4, additive |
| `SIZE_SOFT_FILES`, `SIZE_SOFT_COMMITS`, `SIZE_HARD_FILES` | `15`, `10`, `25` | Mirror `overseer.md:328-329`. The comment cites those lines |
| `FINDINGS_FILE_MAX_BYTES` | `262144` | |
| `FINDINGS_MAX` | `50` | |
| `_EPOCH_MAX_SIBLING_PRS` | `50` | More than this many sibling PRs for one cid is exit 1 |
| `_ISSUE_EVENTS_MAX_PAGES` | `10` | Passed as `max_pages` to `github.list_issue_events` (§3.17) |
| `_LEGACY_PROCEDURAL_PREFIXES` | `("register-missing", "register-missing-role:", "register-missing-fields:", "register-unresolved-escalation:")` | **[AR1-C3]** the `check_register_completeness` token forms |
| `_LEGACY_REQUIRED_CHECK_PREFIX` | `"check-failing:"` | **[AR1-C3]** the `check_required_content_checks` token form |

### 3.2 Data shapes (frozen dataclasses unless noted)

```
Decision        question: str; options: tuple[Option, ...]          # Option = (label: str, text: str)
Conflict        reviewer: str; ref: str                             # ref is a same-repo GitHub URL
Finding         cls: str; key: str; identity: tuple; origin: "code"|"llm";
                path: str|None; summary: str; detail: str; source_url: str|None;
                decision: Decision|None; conflicts_with: Conflict|None
                is_decision -> bool  (property: decision is not None)
PriorFinding    finding_id: str; cls: str; key: str; identity: tuple; origin: str
ReviewerAct     kind: "APPROVED"|"CHANGES_REQUESTED"|"DISMISSED"|"NEEDS_AI_LABEL";
                source_id: int; at: str (GitHub ISO); option_label: str|None
EscalationRecord pr: int; head_sha: str; trigger: str; created_at: str (GitHub ISO);
                option_labels: tuple[str, ...]
PrClosure       pr: int; kind: "merged"|"closed"; at: str; actor_login: str; actor_type: str
Block           kind: "PATH_HOLD"|"UNKNOWN_SCOPE"|"PATH_PENDING_ESCALATION"; source_pr: int; ref: str
VetoState       Enum: NOT_APPLICABLE | NEEDS_START | OPEN | LAPSED
Disposition     Enum (value = wire string): LEGACY, PROCEED, BOUNCE, NOOP, ESCALATE, HOLD,
                HOLD_VETO, HUMAN_SENDBACK, RULING_REQUIRED
CidResolution   cid: str; source: "issue"|"pr-fallback"; issue: int|None; warn: str|None
ReviewerResolution login: str; source: "codeowners"|"machine-accounts.env"; team_owners: tuple[str,...]; note: str|None
```

`RouteInputs` (frozen). **It has no tier, surface, security or CODEOWNERS-ownership field**, so REQ-2
holds by construction (pinned by T-RP-P5):

| Field | Type | S1a CLI supplies |
|---|---|---|
| `pr` | `int` | the PR number **[AR1-C2]** |
| `worker_authored` | `bool` | computed (§3.13 step 4) |
| `head_sha` | `str` | `pr.head.sha` |
| `findings` | `tuple[Finding, ...]` | code + LLM, canonical |
| `collectors_complete` | `bool` | **always `False`** (TD-D4) |
| `hold_on_head` | `bool` | §3.10 |
| `prior_on_head` | `tuple[PriorFinding, ...]` | §3.6 |
| `epoch_bounce_count` | `int` | §3.5 |
| `reviewer_act_on_head` | `ReviewerAct \| None` | `latest_reviewer_act(..., since=None)` |
| `escalation` | `EscalationRecord \| None` | latest `human-required` with `trigger` for `(cid, head)` |
| `escalation_act` | `ReviewerAct \| None` | `latest_reviewer_act(..., since=escalation.created_at)` |
| `blocks` | `tuple[Block, ...]` = `()` | **`()` (S1b)** |
| `pending_rulings` | `tuple[str, ...]` = `()` | **`()` (S1b)** |
| `upheld_unescalated` | `tuple[str, ...]` = `()` | **`()` (S1b)** |
| `withdrawn_on_head` | `frozenset[str]` = `frozenset()` | **empty (S1b)**: finding **ids** (§6.3 R-7) |
| `veto` | `VetoState` = `NOT_APPLICABLE` | **`NOT_APPLICABLE` (S1b)** |

`RouteResult` (frozen): `disposition: Disposition`, `rule: str` (for example `"1"`, `"2c"`, `"6e"`),
`trigger: str|None`, `to_bounce: tuple[Finding, ...]`, `open_findings: tuple[Finding, ...]`,
`overruled_keys: tuple[str, ...]`, `actions: tuple[str, ...]` (the ordered concatenation of every action that the evaluated
rules attach, rule 4's first. This slice has two: `"start-veto-window"` (rules 2 and 4) and
`"repair-finalize"` (rule 6c) [AR4-1]), and `reasons: tuple[str, ...]` (closed tokens, listed in §3.8).

### 3.3 The findings file and canonicalization

`canonicalize_findings(raw: object, *, changed_paths: Sequence[str], head_check_runs: Sequence[str], repo_slug: str) -> tuple[Finding, ...]`
raises `FindingsSchemaError(ValueError)` with a message that names the offending index and field.

- The top level must be exactly `{"findings": [ ... ]}`, with at most `FINDINGS_MAX` entries. The file is
  read as UTF-8 and is at most `FINDINGS_FILE_MAX_BYTES`. A missing file, an oversize file or invalid
  JSON raises the same error.
- **Allowed keys per entry** (anything else is refused, including `key`, `origin` and `id`):
  - `class` (must be in `LLM_FINDING_CLASSES`; `PROCEDURAL` and `REQUIRED_CHECK` are refused with
    "class reserved for code collectors");
  - `summary` (str, 1-200 characters, no newline, must not start with `/hos`);
  - `detail` (str, 0-2,000 characters). Newlines are collapsed to single spaces when rendered;
  - `path` (str or null);
  - `slug` (`MERITS`, `SCOPE`, `REVIEW_FINDING`; required; `^[a-z0-9-]{3,40}$`);
  - `check_run` (`CHECK` only; required; must equal a check-run name on the head, case-sensitive);
  - `rule` (`CHECK` only; optional; `^[A-Za-z0-9._-]{1,40}$`; `-` when absent);
  - `source_url` (optional; must match `^https://github\.com/<owner>/<repo>/` for `repo_slug`, with
    owner and repo compared case-insensitively);
  - `decision` (optional object `{question: str, options: [{label, text}, ...]}`);
  - `conflicts_with` (optional object `{reviewer: ^[a-z0-9-]{2,40}$, ref: same-repo URL}`).
- **Path canonicalization:** NFC-normalize, strip one leading `./`, keep the case, and include no line
  number. A path containing `:<digits>` at its end is refused ("no line numbers"). The canonical path
  must be **exactly** one of `changed_paths` (also NFC-normalized, compared case-sensitively, because
  git paths are case-sensitive). Otherwise it is refused.
- **Keys:** `CHECK` → `check:<check_run>:<rule|->:<path|->`. `MERITS`, `REVIEW_FINDING`, `SCOPE` →
  `<CLASS>:<path|->:<slug>`. Code-collected → `<CLASS>:<check_id>` (§3.11). The identity follows
  TD-D2.
- **Decision validity (AD-1, decided by code):** after `strip()`, a decision with an empty `question`,
  fewer than two options, duplicate labels or duplicate texts, or a label outside
  `^[A-Za-z0-9-]{1,20}$`, is **dropped**. The finding stays a rejection, and the result records
  `reasons += ("decision-malformed:<index>",)`. A `decision` that is not an object, or whose options are
  not objects, is a schema error.
- Two entries with the same key: the first is kept and the rest are dropped, with a reason recorded.
  This is never an error.

### 3.4 `bounce_cid`

```
bounce_cid(pr: dict, *, worker_login: str,
           issue_lookup: Callable[[int], Optional[dict]]) -> CidResolution
```
It is pure apart from the injected lookup. It returns `issue-<N>` (source `issue`) only when **all** of
these hold, read from the payload:
1. `pr.user.login` equals `worker_login` (case-insensitive) **and** `pr.user.type == "Bot"`;
2. `pr.head.ref` matches `^worker-(\d+)-`, which gives N with no leading zeros (the
   `create_branch.sh` format);
3. `pr.head.repo.full_name` equals `pr.base.repo.full_name` (case-insensitive), so the branch is not
   from a fork;
4. `issue_lookup(N)` returns a dict that is **not** a pull request (no `pull_request` key). Its state
   may be open or closed.

Otherwise it returns `pr-<number>` (source `pr-fallback`) with `warn` naming the first failed condition
(`not-worker-author`, `ref-not-worker-format`, `fork-head`, `issue-not-found`, `number-is-a-pr`).

**Fail-closed rule:** `issue_lookup` raising `GitHubError` (a timeout, 5xx, 403 or 429) **propagates**.
It never falls back to `pr-<n>`, because that fallback would hand out a fresh budget, which is the AF-1
escape. Only a `None` result (a 404 or an empty body, F6) counts as "not found". No PR text is parsed
(ADR AD-3).

### 3.5 Epoch and `bounce_count`

```
bounce_count(cid, *, repo_root=".", since: Optional[str] = None) -> int        # existing, additive kwarg
bounce_events(cid, *, repo_root=".") -> list[dict]                             # all pr-bounced for cid
escalation_records(cid, *, repo_root=".") -> list[EscalationRecord]            # human-required with cid+trigger
epoch_start(*, this_pr_created_at: str, escalations: Sequence[EscalationRecord],
            sibling_closures: Sequence[PrClosure], worker_login: str) -> Optional[str]   # pure
```
- **`bounce_count(since=None)`** keeps today's behaviour exactly. With `since`, it counts only the
  events whose **event time** is strictly later than `since`. The event time is `comment_created_at`
  (the GitHub time, new in §3.6) when present, otherwise `timestamp`. An event whose time cannot be
  parsed is **counted**: an unparseable time pushes toward the cap and an earlier escalation, never
  toward a merge.
- **`epoch_start`** returns the latest of:
  - when `EPOCH_RESETS_AT_ESCALATION`, the latest `escalations[].created_at`, on any PR of the cid;
  - the latest `sibling_closures[].at` where `at < this_pr_created_at` and the actor is a non-worker,
    meaning `actor_login` is not `worker_login` (case-insensitive). The overseer and the human-proxy
    count as non-worker.

  If neither applies, it returns `None`, which means the whole history.
- **Sibling closures (CLI):** these are the distinct `pr` values other than this PR among the cid's
  `pr-bounced` and `human-required` events. There can be at most `_EPOCH_MAX_SIBLING_PRS` of them; more
  is exit 1. For each sibling, `get_pull` is read:
  - if `merged_at` is set: `PrClosure(kind="merged", at=merged_at, actor=merged_by)`. **A merged sibling
    with no `merged_by.login` is exit 1**, with `error_code: epoch_sibling_missing` and
    `error_class: deterministic`, for the same reason as the closed-sibling rule below: without the
    actor, a worker merge (no reset) and a non-worker merge (reset) cannot be told apart;
  - if it is closed but not merged: the **latest** `closed` event from `github.list_issue_events` supplies the
    actor. **A closed sibling with no `closed` event (or one with no actor) is exit 1**, with
    `error_code: epoch_sibling_missing` and `error_class: deterministic`. Without an actor,
    the code cannot tell whether a worker closure (which does not reset) or a non-worker closure (which
    does) occurred. Code-review SHOULD_FIX 5;
  - if it is open: nothing.

  Any `GitHubError`, or a `None` PR, is exit 1. That is never "no reset", because a wrong epoch can only
  be resolved by retrying.
- **`epoch_bounce_count`** = `bounce_count(cid, since=epoch_start(...))`.
- `escalation_records` reads `human-required` events carrying a non-empty `cid` equal to this cid and a
  `trigger` in `ESCALATION_TRIGGERS`. It uses `escalation_created_at` as `created_at` and `options`
  (a list of labels, when present) as `option_labels`. Legacy `human-required` events, which carry no
  cid or trigger (AF-4), are ignored. **Nothing writes such records in S1a.** `record-escalation` is S1b.
- Any `ValueError` from `read_stream` (a malformed record) propagates, and the CLI exits 1 (R-3). An
  absent `audit/log/` yields an empty history. That is the #1803 lost-log case: it gives a fresh budget,
  which means more worker iterations, never a merge. §6.3 records it as an S1b availability item.

### 3.6 Same-head dedup, finding ids and `record_pr_bounce`

```
bounced_on_head(cid, head_sha, *, repo_root=".") -> tuple[PriorFinding, ...]
next_finding_index(prior: Sequence[PriorFinding]) -> int        # 1 + max k over "<head12>-F<k>", else 1
record_pr_bounce(owner, repo, pr_number, *, cid, reason_category, summary,
                 failures: Sequence[str] = (),                  # was required; now defaulted
                 label="needs-ai", repo_root=".",
                 head_sha: Optional[str] = None,                # new
                 findings: Optional[Sequence[Finding]] = None,  # new
                 epoch_since: Optional[str] = None,             # new
                 cap: Optional[int] = <BOUNCE_CAP>,             # #2272: default read at call time; None = opt-out
                 ) -> BounceResult
BounceResult += skipped: bool = False; finding_ids: list[str] = []; finalize_repaired: list[str] = []; at_cap: bool = False
```
- `bounced_on_head` reads every `pr-bounced` event with `cid == cid` and `head_sha == head_sha`. It
  returns each `findings[]` entry. A legacy event (no `findings`) has each `failures` token mapped by
  `legacy_token_finding(token) -> (cls, key, identity)` **[AR1-C3]**, with `finding_id=""` and
  `origin="code"` for the first two rows below:

  | Token | `cls` | `key` | `identity` |
  |---|---|---|---|
  | `== "register-missing"`, or starts with `register-missing-role:`, `register-missing-fields:` or `register-unresolved-escalation:` | `PROCEDURAL` | `PROCEDURAL:<token>` | `("PROCEDURAL", key)` |
  | starts with `check-failing:` | `REQUIRED_CHECK` | `REQUIRED_CHECK:<token>` | `("REQUIRED_CHECK", key)` |
  | anything else | `LEGACY` | `<token>` | `("LEGACY", token)` (`origin="legacy"`) |

  These are exactly the keys and identities §3.11's collectors produce for the same token. A legacy 4a
  or 4c bounce at cutover, followed by `route` or `bounce` on the same head, is therefore a same-head
  repeat and not a second bounce (T-BG-10).
- **The `record_pr_bounce` algorithm, in order:**
  1. Validate `reason_category` (it raises `ValueError` first, before any I/O, as today). If `findings`
     is given, `failures` must be empty and `head_sha` must be given; otherwise `ValueError`.
  2. If `head_sha` is `None`: `_run_gh(["/repos/{o}/{r}/pulls/{n}"])`. Its `head.sha` must be non-empty,
     otherwise `GitHubError` (TD-D5).
  3. **Dedup.** The new key set is `[f.key for f in findings]`, or, on the legacy path,
     `[legacy_token_finding(t).key for t in failures]` **[AR1-C3]**. The prior key set is
     `{p.key for p in bounced_on_head(cid, head_sha)}`. If the new set is non-empty
     and is a subset of the prior set, the call **skips**. It calls `repair_bounce_finalize`
     (TD-D9), which reads `GET /pulls/{n}` for `draft` and `labels`, plus the issue events in the
     ambiguous state. It returns
     `BounceResult(comment_url=None, audit_relpath="", bounce_number=<count>, skipped=True, finalize_repaired=[...])`.
     A label or draft write failure is appended to `finalize_errors` and does not raise. A failed or
     truncated **read** (the PR or the issue events) raises [codex second review].
  4. `bounce_number = bounce_count(cid, since=epoch_since) + 1`. Before that, unless `cap is None`, a
     count `>= cap` posts and writes nothing and returns `skipped=True, at_cap=True` (#2272).
  5. Assign ids. When `findings` is given:
     `"<head_sha[:12]>-F<k>"` for `k = next_finding_index(prior), next_finding_index(prior)+1, …`, in
     input order.
  6. Render the body (§3.7), post it, and confirm the read-back (unchanged; it raises).
  7. Write the event (§3.15; it raises on failure).
  8. Finalize the label and the draft (unchanged, best-effort).
- `route` passes `head_sha`, `findings`, `epoch_since=epoch_start` and the derived `reason_category`
  and `summary` (§3.7). Today's improvised callers keep working, gain step 2 and step 3, and keep
  `bounce_number` all-time (`epoch_since=None`).

### 3.7 The bounce comment

`_bounce_comment_body(failures, reason_category, summary, bounce_number)` keeps its signature and now
returns the **legacy rendering**. A new
`_bounce_comment_body_findings(findings_with_ids, reason_category, summary, bounce_number, *, cid, head_sha)`
returns the **findings rendering**. Both start with the same heading and section, so the S3 worker
re-entry text has one format to parse (VF-5).

**Findings rendering (AD-4, exact):**
```
## PR bounced to the worker: <n> finding(s) on <head12>

### Specific failures
- [<finding-id>] (<CLASS>) <summary>. <detail>[ (<source_url>)]

### How to respond
Fix each finding, or dispute one: post a comment whose first line is `/hos dispute <finding-id>`, followed by your reason.

**Reason category:** <category>
**Summary:** <summary>

_Bounce #<k> for <cid> (cap: 2 before human escalation)._
```
- `<n>` is the number of findings in **this** bounce. `<detail>` has its newlines collapsed. When
  `detail` is empty, the `. <detail>` part is omitted. The cap number comes from `BOUNCE_CAP`.
- `reason_category = derive_reason_category(classes)`. When all findings share one class, the mapping is
  `PROCEDURAL → REGISTER_GAP`, `REQUIRED_CHECK → COMPLIANCE_FAILURE`, `CHECK → CHECK_FAILURE`,
  `MERITS → MERITS_FINDING`, `SCOPE → SCOPE_SIZE` and `REVIEW_FINDING → REVIEW_FINDING`. Mixed classes
  give `MIXED`.
- `summary` (templated, never LLM text):
  `"<n> finding(s) on <head12> must be fixed or disputed before this PR can proceed."`

**Legacy rendering:** the same heading, with `<head12>` taken from the resolved head (TD-D5), and the
same `### Specific failures` section. Each failure becomes `- [<id>] <text>`, where:
- a token matching `^[A-Za-z0-9._:-]+$` is its own `<id>`, and `<text>` comes from this gloss table:
  - `register-missing` → "Sign-off register is missing";
  - `register-missing-role:<r>` → "Required sign-off missing: <r>";
  - `register-missing-fields:<r>:<f>` → "Sign-off <r> is missing field(s) <f>";
  - `register-unresolved-escalation:<r>` → "Sign-off <r> is ESCALATED with no Human_resolution";
  - `check-failing:<n>` → "Required check <n> is failing";
  - any other token → the token itself;
- any other string gets `<id> = item-<k>` (1-based) and `<text>` = the string.

The legacy rendering has **no** "How to respond" section and no dispute text. It then has
`**Reason category:**`, `**Summary:**` and the bounce line, as today. "procedural completeness" appears
in neither rendering (VF-4). Neither contains `Expected action`, `REQUEST CHANGES` or `needs-human`
(REQ-5).

**Size cap and neutralization (security SF1/SF2, implemented in S1a):**
- **Size cap.** The rendered body is capped below GitHub's 65,536-character comment limit, in two
  steps:
  1. Each finding's `detail` is truncated first.
  2. If the body is still too long, the remaining findings are rendered as `[<id>] (<CLASS>) <summary>`
     only, followed by one line `N findings truncated`.

  The `pr-bounced` audit event always lists every finding, untruncated.
- **Neutralization.** In LLM-supplied text:
  - `@`-mentions are neutralized, so a bounce cannot notify anyone;
  - image markdown (`![...](...)`) is neutralized;
  - a `source_url` or `conflicts_with.ref` containing a `..` path segment is rejected at schema
    validation.

### 3.8 `route_pr` — the precedence list (pure; first match wins)

`route_pr(inputs: RouteInputs) -> RouteResult`. Let `code_open` be the findings with `origin == "code"`,
`rejections` the findings that are not decisions and whose id is not in `withdrawn_on_head` (S1a: all
non-decision findings), and `decisions` the decision findings. **[AR1-C2]** Let `pending_blocks` be the
`PATH_PENDING_ESCALATION` blocks whose `source_pr != inputs.pr`. A pending-escalation block sourced from
this PR is ignored everywhere. `PATH_HOLD` and `UNKNOWN_SCOPE` blocks are never filtered by `source_pr`.
**[AR1-C1]** Let `veto_action = ("start-veto-window",)` if `veto == NEEDS_START`, else `()`. Every
rule-2 result carries `actions = veto_action`. **[AR4-1]** Outside rule 2, `actions` is the ordered
concatenation of every action that the evaluated rules attach. Rule 4's comes first, and a later rule
**appends** to it, so rule 4 followed by 6c gives `("start-veto-window", "repair-finalize")`.

| Rule | Condition | Result (`disposition`, `trigger`, reason token) |
|---|---|---|
| 1 | `not worker_authored` | `LEGACY`, `non-worker-pr` (ESC-3 A) |
| 1 | any block of kind `PATH_HOLD` or `UNKNOWN_SCOPE` | `LEGACY`, `path-hold` |
| 1 | `hold_on_head` | `LEGACY`, `hold-902` |
| 2 | `escalation` is set, and `escalation_act` is `None` | `HOLD`, `awaiting-reviewer` |
| 2 | … the act is `DISMISSED` | `HOLD`, `approval-revoked` |
| 2 | … the act is `CHANGES_REQUESTED` or `NEEDS_AI_LABEL` | `HUMAN_SENDBACK` |
| 2 | … `APPROVED`, but `code_open` is non-empty | `HOLD`, `code-findings-open` |
| 2 | … `APPROVED`, but `not collectors_complete` | `HOLD`, `collectors-incomplete` |
| 2 | … `APPROVED`, trigger `decision`, and `option_label` is not in `option_labels` | `HOLD`, `decision-option-missing` |
| 2 | … `APPROVED`, and `pending_rulings` is non-empty | `RULING_REQUIRED` [AR4-2, Q5 option (1)] |
| 2 | … `APPROVED`, and `upheld_unescalated` is non-empty | `ESCALATE`, `upheld-dispute` [AR4-2, Q5 option (1)] |
| 2 | … `APPROVED`, and the veto is `NEEDS_START` | `HOLD_VETO`, `actions=("start-veto-window",)` (TD-D10, AR1-C1) |
| 2 | … `APPROVED`, and the veto is `OPEN` | `HOLD_VETO`, no action (TD-D10, AR1-C1) |
| 2 | … `APPROVED`, and `pending_blocks` is non-empty | `HOLD`, `path-pending-escalation` (TD-D10, AR1-C2) |
| 2 | … `APPROVED` otherwise | `PROCEED`, with `overruled_keys` = the LLM finding keys |
| 3 | `pending_rulings` is non-empty | `RULING_REQUIRED` |
| 4 | the veto is `NEEDS_START` | adds the action `start-veto-window`, treats the veto as `OPEN`, and **continues** |
| 5 | `upheld_unescalated` is non-empty | `ESCALATE`, `upheld-dispute` |
| 6a | rejections exist, and `reviewer_act_on_head.kind == "APPROVED"` | `ESCALATE`, `reviewer-conflict` (ESC-2 C) |
| 6b | rejections exist, and any has `conflicts_with` | `ESCALATE`, `reviewer-conflict` |
| 6c | rejections exist, and every identity is in `{p.identity for p in prior_on_head}` | `NOOP`, `no-new-keys`; **appends** `repair-finalize` to `actions` [AR4-1]. `prior_on_head` is always non-empty here [codex second review] |
| 6d | rejections exist, and `epoch_bounce_count >= BOUNCE_CAP` | `ESCALATE`, `bounce-cap` |
| 6e | rejections exist otherwise | `BOUNCE`, where `to_bounce` = the rejections with a new identity, in input order |
| 7 | `decisions` is non-empty | `ESCALATE`, `decision` |
| 8 | the veto is `OPEN` | `HOLD_VETO` |
| 8 | `pending_blocks` is non-empty (a block from this PR is ignored, AR1-C2) | `HOLD`, `path-pending-escalation` |
| 8 | `not collectors_complete` | `HOLD`, `collectors-incomplete` |
| 8 | otherwise | `PROCEED` |

`open_findings` is always the full rejections list, so an ESCALATE body can list what is still open.
`route_pr` performs no I/O, reads no clock and does not mutate its inputs.

### 3.9 `latest_reviewer_act`

```
latest_reviewer_act(reviews: Sequence[dict], label_events: Sequence[dict], reviewer: str,
                    head_sha: str, since: Optional[str], *, bot_accounts: Collection[str]
                    ) -> Optional[ReviewerAct]
```
1. **Collect reviews.** The review `user.login` must equal `reviewer` (case-insensitive), and
   `not is_bot_reviewer(login, user.type, set(bot_accounts))`. In addition, `commit_id == head_sha`,
   `state` must be in `{APPROVED, CHANGES_REQUESTED, DISMISSED}`, and when `since` is not `None`,
   `submitted_at > since`. A `COMMENTED` review is never collected. A review whose `submitted_at` is
   unparseable is dropped when `since` is set (it cannot be shown to be after the escalation) and kept
   otherwise.
2. **Collect label events, only when `since` is not `None`.** The event must have
   `event == "labeled"`, `label.name == "needs-ai"`, and an actor who is the reviewer and not a bot,
   with `created_at > since`. With `since=None`, label events are ignored, because a label carries no
   head binding.
3. **Choose** the latest by `(parsed time, id)`. Each review or event contributes its own `id`.
4. **Evaluate.** Return `ReviewerAct(kind, source_id, at, option_label)`. `option_label` is taken only
   for `APPROVED` reviews: the first line of the review body matching `^Option:\s*(?P<l>[A-Za-z0-9-]{1,20})\s*$`
   (multiline). The body itself is never returned or logged.

`_find_human_approval` and `has_human_approval` are unchanged (ADR N-1).

### 3.10 The CODEOWNERS base-ref read, reviewer resolution and the #902 check

```
fetch_codeowners_text(owner, repo, ref) -> Optional[str]
_codeowners_humans_from_text(text: Optional[str]) -> set[str]
resolve_reviewer_from_text(text, changed_files, *, bot_accounts, human_reviewer) -> ReviewerResolution
effective_head_time(committer_date: Optional[str], check_suites: Sequence[dict]) -> Optional[str]
```
- **`fetch_codeowners_text`** (in `merge_authority.py`) tries, in order, `.github/CODEOWNERS`,
  `CODEOWNERS` and `docs/CODEOWNERS` through `github.get_contents(owner, repo, path, ref=<base_sha>)`
  **[AR1-C5]**. A `None` result (404) moves on to the next path. The first payload must have `encoding == "base64"` and a non-empty
  `content`, which is decoded as UTF-8. Anything else (a file over 1 MB is returned with no content, a
  decode error, a non-dict) raises `GitHubError`. `GitHubError` propagates, and the CLI exits 1. If all
  three return `None`, the result is `None`, meaning there is no CODEOWNERS file.
- **`_codeowners_humans_from_text`** is byte-equivalent to `requester_trust.codeowners_humans` (the same loop), over
  the given text: skip blank and `#` lines, take the owners after the pattern, strip `@`, skip any owner
  containing `/`, and lowercase. `None` gives `set()`.
- **`resolve_reviewer_from_text`** loads `scripts/oversight/codeowners.py` by path. It then applies the
  same steps as `resolve_human_reviewer`, but on `text`:
  - `None` → (`human_reviewer`, `machine-accounts.env`, note `no CODEOWNERS file`);
  - otherwise it accumulates owners across `sorted(changed_files)` using `get_owners_for_path`, and
    splits them into team, e-mail, bot and user owners with that module's `_is_team`,
    `_owner_is_email` and `_owner_is_bot`;
  - the first user owner wins (`@` stripped, source `codeowners`);
  - otherwise the result is `human_reviewer`, with the same note strings.

  **A team-owned path therefore falls back to `HUMAN_REVIEWER`, exactly as in step 6.** E-mail owners
  never appear in the result.
- **The drift guard (TD-D3):** when the source is `codeowners`, `login.lower()` must be in
  `_codeowners_humans_from_text(text)`.
- **`effective_head_time` [AR1-C7]** takes the check suites from
  `github.list_check_suites_for_ref(owner, repo, head_sha)` and keeps those whose `app.slug` is
  `"github-actions"` and whose `head_sha` equals the head. It takes the earliest parseable `created_at`
  among them (the bound `B`). It returns `min(committer_date, B)` when both exist, `B` when only `B`
  exists, and `None` when no such suite exists, even if a committer date exists. A committer date is
  never trusted alone. The status of the suite's runs is irrelevant, so a head whose runs are all still
  `queued` is bounded.
- **The #902 check in `route`:**
  `hold_on_head = any(detect_human_hold_directive(comments, login, effective_head_time(...)) is not None for login in {config.human_reviewer, resolved.login})`.
  The logins are deduplicated case-insensitively.
- Issue events come from `github.list_issue_events(owner, repo, n, max_pages=_ISSUE_EVENTS_MAX_PAGES)`
  (§3.17). `merge_authority.py` has no issue-events reader of its own **[AR1-C5]**.

### 3.11 Code collectors (`collect_code_findings`, shared by `route` and `bounce`)

```
collect_code_findings(owner, repo, *, step, head_sha, pr: dict, changed_paths, repo_root,
                      default_branch) -> tuple[tuple[Finding, ...], dict]     # (findings, evidence)
```
| Collector | Source | Finding (class, key) |
|---|---|---|
| register | `check_register_completeness(step, repo_root=...)` | `PROCEDURAL`, `PROCEDURAL:<failure>`, one per failure |
| required checks | `check_required_content_checks(owner, repo, head_sha, default_branch=...)` | `REQUIRED_CHECK`, `REQUIRED_CHECK:<failure>`, for example `REQUIRED_CHECK:check-failing:tests` |
| size | `len(changed_paths)`, `pr["commits"]` | `SCOPE`, `SCOPE:size-hard-ceiling` (> 25 files); `SCOPE:size-soft-files` (> 15); `SCOPE:size-soft-commits` (> 10) |
| validator artifact (AF-5) | **S1b** | — |

- The `summary` text is templated (for example `"Changed files 31 exceed the 25-file hard ceiling; split the PR."`).
  `detail` is `""`, and `path` is `None`.
- `evidence` records each collector's raw result. A **degraded** required-checks read (its result has
  `bounce_required=False` and a summary that starts with `"required-checks gate skipped"`) sets
  `evidence["required_checks_degraded"] = True`. `route` adds that to `not_verified`. Rule 8 already
  holds the PR in S1a (TD-D4), and S1b must treat a degraded read as `collectors_complete = False`
  (§6.3).
- `list_check_runs_for_ref` raising (inside `check_required_content_checks`) propagates, and the CLI
  exits 1.

### 3.12 The CLI: common rules for `route` and `bounce`

- `SUBCOMMANDS` gains `"route"` and `"bounce"`. Both are added to `NETWORK_SUBCOMMANDS`.
- They use a separate parent parser: `--app` has `choices=("overseer",)` (TD-D8), and `--repo` is
  optional. The flags are `--pr` (required, `_pr_type`) and `--step` (required, `_step_type`). `route`
  also takes `--findings-file <path>` (required). No `--head-sha`, `--force`, `--config`, `--manifest`
  or `--repo-root` exists (T1.7 extends to both).
- **Exit codes:** 0 means a disposition was decided and any write it called for succeeded. 1 is an
  operational error, with no further writes. 2 is a usage error. **3 is reserved for `route`'s
  `RULING_REQUIRED` and is unreachable in S1a** (its input is empty).
- **The identity check runs first, before any fetch:** `HOS_BOT_LOGIN` must equal
  `config.overseer_handle`. Otherwise exit 1, `acting_identity_not_overseer`.
- **The head pin:** the handler re-reads `get_pull` after all reads and before any write. If `head.sha`
  changed, it exits 1 with `head_moved` and writes nothing.
- **The file-list completeness check:** after `list_pull_files`, a length different from
  `pr["changed_files"]` is exit 1 with `changed_files_mismatch` (transient: a push raced the reads). A
  length of 3,000 or more is exit 1 with `changed_files_truncated` (deterministic).
- **`error_class` [AR1-C6]:** every exit-1 record carries a payload key `error_class` with the value
  `transient` or `deterministic`, plus `error_code`, the closed token named in §3.16. Exit 0 and exit 2
  records carry `error_class: null`. A `GitHubError` is classified by
  `classify_github_error(exc) -> "transient" | "deterministic"`, which lives in `merge_authority.py`:
  - **transient:** `RateLimitError`, `status_code is None` (a timeout, network failure, or an
    unparseable `gh` failure), or `status_code >= 500`;
  - **deterministic:** every other status (a 4xx other than a 429, or a 403 that `_run_gh` did not
    raise as a rate limit).

### 3.13 `route` — the handler sequence

`merge_authority.sh route --app overseer --pr <n> --step <N> --findings-file <p> [--repo <o/r>]`

1. Check the identity, resolve the repo and read the findings file as bytes. A read or JSON error is
   exit 1 with `findings_file_invalid`. The file is parsed after step 6, once its validation inputs are
   known.
2. `pr = get_pull`. `None` or a missing `head.sha` is exit 1. A `state` other than `open` is exit 1 with
   `pr_not_open`.
3. `cid = bounce_cid(pr, worker_login=config.worker_handle, issue_lookup=get_issue)`. A fallback adds
   `not_verified: "cid: pr-<n> fallback (<warn>)"` and writes the same text to stderr as `WARN:`.
4. `worker_authored = (user.login == config.worker_handle, case-insensitive) and user.type == "Bot"`.
   **If it is false, call `route_pr` with only this input set and emit `LEGACY` (ESC-3 A). No further
   fetch is made.**
5. `files = list_pull_files`, followed by the completeness check (§3.12). `changed_paths` are the
   NFC-normalized `filename` values.
6. `check_runs = list_check_runs_for_ref(head)`. `findings_llm = canonicalize_findings(...)`, where a
   `FindingsSchemaError` is exit 1 with `findings_schema: <msg>`.
7. `code_findings, evidence = collect_code_findings(...)`.
8. Audit reads: `bounce_events`, `escalation_records`, `bounced_on_head`. A `ValueError` is exit 1 with
   `audit_unreadable`.
9. Sibling closures, then `epoch_start`, then `epoch_bounce_count` (§3.5).
10. `text = fetch_codeowners_text(base.sha)`, `resolved = resolve_reviewer_from_text(...)`, then the
    drift guard.
11. `reviews = list_pull_reviews`. If an escalation record for `(cid, head)` exists:
    `label_events = github.list_issue_events(..., max_pages=_ISSUE_EVENTS_MAX_PAGES)`.
12. `comments = list_issue_comments`, `commit = get_commit(head)`,
    `suites = github.list_check_suites_for_ref(head)` (AR1-C7), and then `hold_on_head` (§3.10).
13. `result = route_pr(RouteInputs(...))`, with the S1b fields at their defaults.
14. The head pin (§3.12).
15. **Execute:** a `NOOP` carrying `repair-finalize` calls `repair_bounce_finalize` (TD-D9), and the
    payload's `bounce` becomes `{skipped: true, finalize_repaired, finalize_errors}`. Its read failure is
    exit 1 (§3.16). Otherwise only `BOUNCE` writes in S1a, through
    `record_pr_bounce(..., head_sha, findings=result.to_bounce, epoch_since=epoch_start, reason_category=derive…, summary=…)`.
    A `GitHubError` or audit-write error is exit 1. The payload then states which step failed, and
    whether the comment was already posted (`comment_posted: true|false`).
16. Emit the record and exit 0.

**Payload keys** (pinned in `_PAYLOAD_KEYS["route"]`):
`step`, `cid`, `cid_source`, `head_sha`, `base_sha`, `worker_authored`, `disposition`, `rule`,
`trigger`, `reasons`, `findings` (each `{key, class, origin, path, summary}`, plus `id` when bounced),
`open_finding_keys`, `overruled_keys`, `actions`, `bounce` (`null`, or
`{comment_url, audit_relpath, bounce_number, finding_ids, skipped, finalize_errors, finalize_repaired}`),
`epoch_start`, `epoch_bounce_count`, `bounce_cap`, `reviewer` (`{login, source, note}`),
`reviewer_act` (`null` or `{kind, source_id, at}`), `escalation` (`null` or `{trigger, created_at}`),
`hold_directive` (`null` or `{comment_url, created_at}`), `effective_head_time`, `collectors`
(`{register, required_checks, size, validator_artifact: "not-implemented-s1a"}`), and
`s1b_inputs_stubbed` (always `["blocks","pending_rulings","upheld_unescalated","withdrawn_on_head","veto"]`
in S1a).

`not_verified` always contains `"collectors_complete=false: validator-artifact collector lands in S1b"`
and `"s1b inputs stubbed: path blocks, disputes, veto window not evaluated"`.

### 3.14 `bounce` — the deterministic bounce for code-collected findings (AF-3)

`merge_authority.sh bounce --app overseer --pr <n> --step <N> [--repo <o/r>]`

This is the fixed CLI form of today's 4a/4c call. It follows steps 1-5, 7, 8, 9 and 14 of §3.13. It
reads no findings file and no CODEOWNERS file, and it does no #902 check or reviewer lookup (those are
`route`'s job). Then:
- not worker-authored → exit 0, `bounced: false, reason: "non-worker-pr"`;
- no code findings → exit 0, `bounced: false, reason: "clean"`;
- every key already bounced on this head → `record_pr_bounce` skips (with repair). Exit 0,
  `bounced: false, reason: "same-head", bounce: {...}`;
- `epoch_bounce_count >= BOUNCE_CAP` → exit 0, `bounced: false, reason: "at-cap", at_cap: true`. The
  caller escalates; this subcommand never escalates;
- otherwise → `record_pr_bounce(findings=..., head_sha=..., epoch_since=...)` with the findings
  rendering, then exit 0 with `bounced: true`.

**Payload keys:** `step`, `cid`, `cid_source`, `head_sha`, `bounced`, `reason`, `at_cap`, `findings`,
`bounce`, `epoch_start`, `epoch_bounce_count`, `bounce_cap`, `collectors`.

### 3.15 Audit events (written with `audit_log.write_event(event, root=str(ctx.repo_root))`)

| Event | Change | Fields |
|---|---|---|
| `pr-bounced` | extended (additive) | the existing fields, unchanged. `failures` = the keys bounced; `reason_category` uses the extended set. **New:** `head_sha` (always, including on the legacy path through TD-D5); `findings` (findings path only: a list of `{id, class, key, origin, path}`); `comment_id`, `comment_created_at` (the GitHub `created_at` of the posted comment); `epoch_start` (findings path); `actor` (`HOS_BOT_LOGIN` when set, else `null`). `bounce_number` is epoch-relative on the findings path |

No other event is written in S1a. **Summaries, details and comment bodies are never written**, except
the existing templated `summary` (AD-7).

**Contract update in S1a [AR1-C4].** `contract/OVERSIGHT-CONTRACT.md` changes in two places, both for
`pr-bounced` only. The new S1b events (and the `human-required` extension) stay with S1b's §6a edit.
- **The event-table row (`:440`).**
  - The description becomes "Overseer returned a PR to the worker (register gaps, failing checks,
    merits, scope or review findings); PR left open, labeled `needs-ai`, converted to draft, not a task
    failure".
  - The fields become `pr`, `cid` (`issue-<N>` or `pr-<n>`, per #2209 `bounce_cid`), `bounce_number`
    (epoch-relative on the findings path), `failures` (the bounced keys), `assigned_to`, `repo`,
    `timestamp`, `reason_category` (`REGISTER_GAP | COMPLIANCE_FAILURE | SPEC_AMBIGUITY | OTHER |
    CHECK_FAILURE | MERITS_FINDING | SCOPE_SIZE | REVIEW_FINDING | MIXED`), `summary`, `comment_posted`,
    `head_sha`, `findings` (findings path), `comment_id`, `comment_created_at`, `epoch_start`
    (findings path), `actor`.
- **The JSON schema block (`:448-462`).** It gains the same fields, with these value notes:
  - `"head_sha": "<40-hex head the bounce was computed on>"`;
  - `"findings": [{"id": "<head12>-F<k>", "class": "<FINDING_CLASS>", "key": "<canonical key>", "origin": "code|llm", "path": "<path>|null"}]`,
    present on the findings path only;
  - `"comment_id": <int>` and `"comment_created_at": "<GitHub ISO-8601>"`;
  - `"epoch_start": "<GitHub ISO-8601>|null"`, present on the findings path only;
  - `"actor": "<acting App login>|null"`;
  - the `reason_category` enum extended as in the row.

  One sentence follows the block: "A repeat bounce on the same `(cid, head_sha)` whose keys were all
  already bounced writes no event (#2209 REQ-12). Legacy register and required-check tokens are compared
  under their collector keys (`PROCEDURAL:<token>`, `REQUIRED_CHECK:<token>`)."

### 3.16 Failure behaviour and `error_class` (fail-closed table) [AR1-C6]

Every exit-1 row writes nothing beyond what the row states. The `error_code` is the closed token in the
payload.

| Failure | Where | `error_code` | `error_class` |
|---|---|---|---|
| `HOS_BOT_LOGIN` unset or not the overseer | identity check | `acting_identity_not_overseer` | deterministic |
| `owner/repo` unresolvable | `_resolve_repo_or_fail` | `repo_unresolved` | deterministic |
| Findings file missing, oversize or not JSON | step 1 | `findings_file_invalid` | deterministic |
| Findings schema refusal | `canonicalize_findings` | `findings_schema` | deterministic |
| A `GitHubError` on any read | any read | `github_read_failed` | `classify_github_error` |
| A 404 or empty body on the PR, or a PR with no usable `base.sha` (AF-7 fail-closed: checked immediately after `get_pull`, before any other read, because the CODEOWNERS read must be pinned to the base) | `get_pull` | `pr_not_found` | deterministic |
| The PR is not open | step 2 | `pr_not_open` | deterministic |
| A 404 or empty body on issue N | `bounce_cid` | — (a `pr-<n>` fallback, exit 0, WARN) | — |
| Issue lookup error other than "not found" | `bounce_cid` | `github_read_failed` | `classify_github_error` |
| Changed-file count differs from `pr.changed_files` | §3.12 | `changed_files_mismatch` | transient |
| 3,000 or more changed files | §3.12 | `changed_files_truncated` | deterministic |
| More than `max_pages` of issue events, or a non-list page | `github.list_issue_events` | `issue_events_truncated` | deterministic |
| CODEOWNERS payload unusable (no content, not base64, not UTF-8) | `fetch_codeowners_text` | `codeowners_unreadable` | deterministic |
| CODEOWNERS read raised `GitHubError` | `get_contents` | `github_read_failed` | `classify_github_error` |
| Resolved login not in the humans set | drift guard | `codeowners_resolution_drift` | deterministic |
| More than `_EPOCH_MAX_SIBLING_PRS` siblings | §3.5 | `epoch_siblings_exceeded` | deterministic |
| A sibling PR returns `None` | §3.5 | `epoch_sibling_missing` | deterministic |
| A closed-not-merged sibling has no `closed` event or no actor, or a merged sibling has no `merged_by.login` | §3.5 | `epoch_sibling_missing` | deterministic |
| A malformed audit record | `read_stream` | `audit_unreadable` | deterministic |
| The head moved during the run | the head pin | `head_moved` | transient |
| The comment post (or its read-back) fails | `record_pr_bounce` | `bounce_comment_failed`, `comment_posted: false`, no event | `classify_github_error` |
| The audit write fails after the post | `record_pr_bounce` | `bounce_audit_write_failed`, `comment_posted: true`, no finalize (halt). With no event there is no dedup, so a later cycle may post a duplicate comment; that is the accepted cost. **This also covers a `ValueError` (or any other exception) from `audit_log.write_event`.** `record_pr_bounce` wraps **only** the `write_event` call and re-raises its failure as `BounceAuditWriteError`, so this code always means the comment was posted | deterministic |
| Any other exception in the bounce write path (not a `BounceAuditWriteError`, and not a `GitHubError` classified by the comment or head-read rows above) | `record_pr_bounce`, via the `route` or `bounce` handler | `bounce_unexpected_error`, `comment_posted: null`. **The post state is unknown**, which `null` records explicitly (ops advisory 1). The next cycle's same-head dedup finds no event and may re-bounce, which is the same accepted cost as the row above | deterministic |
| The head read in `record_pr_bounce` fails (TD-D5) | `record_pr_bounce` | `github_read_failed` | `classify_github_error` |
| The label or draft step fails | `record_pr_bounce` | exit 0: `finalize_errors` set, `not_verified` entry, repaired on the next same-head cycle (TD-D9) | — |
| The required-check source is degraded | collector | exit 0: `not_verified` entry. No `PROCEED` in S1a (TD-D4) | — |

**S2 hand-off (binding on S2) [AR1-C6]:**
- **`deterministic`.** A `route` or `bounce` exit 1 with `error_class: deterministic` is surfaced, never
  silently re-skipped. S2's overseer step posts one escalation note per `(pr, head_sha, error_code)`.
  The note names the `error_code`, says what clears it, and names `HUMAN_REVIEWER`.
- **The #1215 precheck suppresses duplicate notes only [AR2-3].** It suppresses only a second note for
  the same `(pr, head_sha, error_code)`. It never suppresses the `route` run itself: **every cycle still
  runs `route`** on the PR. A note is superseded when a later `route` on that head exits 0, or exits 1
  with a different `error_code`, which gets its own note. (A silent re-skip is the #2207 failure.)
- **`transient`, with three strikes [AR2-2; approved, architect round 2].** A transient exit 1 is retried
  on the next cycle, and S2 counts them per `(pr, head_sha)`:
  - **How S2 counts.** S2 persists each transient exit 1 of `route` or `bounce` as an audited,
    code-written event `{pr, head_sha, error_code}` written through `audit_log`. S2's TD names the event.
    S2 never counts from prose, memory or its own cycle notes.
  - **What "consecutive" means.** No exit-0 `route` on that `(pr, head_sha)` falls between the counted
    events. An exit 0 resets the count, and so does a new head.
  - **The third strike.** The third consecutive transient exit is treated as deterministic. The
    resulting note says the error was transient three times on this head, and lists the `error_code`s.
    This mirrors AD-5a's merge-failure cap of 3.
  - **S1a's part.** S1a writes nothing extra for this: no event, and no counter. Its only contribution
    is the `error_class` and `error_code` in the payload.
- **`findings_file_invalid` and `findings_schema` are the overseer's to fix [AR2-4].** The findings file
  is the overseer's own output, so S2 does not escalate these on first sight.
  - **First occurrence.** The overseer regenerates the findings file and re-runs `route` in the same
    cycle.
  - **Second occurrence.** Only when the same `error_code` recurs on the same head, in a second
    consecutive cycle, is it surfaced as deterministic, with one note naming `HUMAN_REVIEWER`.
  - **Classification.** The §3.16 classification of both codes stays `deterministic`. This rule changes
    only S2's handling.

(Repeated **compare** failures are an S1b item, §6.3.)

### 3.17 `scripts/automation/lib/github.py` additions [AR1-C5]

All three follow the module's existing conventions: REST-by-id, never Search; paginate with
`per_page=100`; a non-list page, or more than `max_pages` full pages, raises `GitHubError`, and a
truncated list is never returned (the `get_ruleset_required_checks` pattern); `None` means 404.

```
list_issue_events(owner, repo, number, *, max_pages: int = 10) -> list[dict]
    GET /repos/{o}/{r}/issues/{n}/events?per_page=100&page=k  (oldest first)
get_contents(owner, repo, path, *, ref: str) -> Optional[dict]
    GET /repos/{o}/{r}/contents/{quote(path)}?ref={ref}.  None on 404. A list payload (a directory)
    raises GitHubError. Decoding is the caller's job
list_check_suites_for_ref(owner, repo, ref, *, max_pages: int = 10) -> list[dict]
    GET /repos/{o}/{r}/commits/{ref}/check-suites?per_page=100&page=k -> the "check_suites" lists, concatenated.
    A page that is not a dict with a list "check_suites" raises GitHubError
```

S1b's compare and timeline reads are also added to `github.py` (§6.1). The tests for these three live
in `test_route_pr.py` (T-GH-*), which keeps the file count down.

### 3.18 `bootstrap/merge_authority.sh`

- **Header:** the first line becomes "L3 wrapper for the merge-authority primitive surface: read-only
  queries (#1357) plus the overseer's route and bounce (#2209)." The usage block gains the two
  subcommands. The "Read-only" paragraph is rewritten to say that `route` and `bounce` write (a comment,
  an audit event, a label, the draft state), only with `--app overseer`, and that every other
  subcommand stays read-only. The exit-code block says: "3 — `route` only: ruling-required (unreachable
  until #2209 S1b)."
- **Mint:** add a `route|bounce)` case that sets `MINT_TOKEN=true` only for `APP_ROLE == overseer`. Other
  roles mint nothing, and Python then returns exit 2. No other logic changes. The wrapper still never
  emits JSON.

---

## 4. S1a files (10) [AR1-C4, AR1-C5]

| # | File | Change |
|---|---|---|
| 1 | `scripts/automation/lib/merge_authority.py` | §3.1-§3.11 and §3.15: constants; dataclasses; `canonicalize_findings`; `bounce_cid`; `bounce_events`, `escalation_records`, `epoch_start` and the `since` keyword on `bounce_count`; `bounced_on_head`, `next_finding_index`; the `record_pr_bounce` keywords and steps 2, 3 and 5; both renderings and `derive_reason_category`; `route_pr`; `latest_reviewer_act`; `legacy_token_finding` (C3); the CODEOWNERS fetch (over `github.get_contents`), parser and resolver; `effective_head_time` (over check suites, C7); `collect_code_findings`; the `error_class` classifier (C6). All additive |
| 2 | `scripts/automation/merge_authority_cli.py` | §3.12-§3.14: the `route` and `bounce` handlers, the overseer-only parent parser, the identity check, the head pin and file-list check, the payload keys. The first docstring line becomes "L2 primitives over merge_authority.py: read-only queries (#1357) plus the overseer's route and bounce (#2209)." The other eight subcommands are unchanged |
| 3 | `bootstrap/merge_authority.sh` | §3.18 |
| 4 | `tests/automation/test_bounce_gate.py` | Update the existing `record_pr_bounce` tests for TD-D5 (patch the head read; `test_comment_post_failure` and the halt tests patch `_run_gh` as well); add T-BG-* (§5) |
| 5 | `tests/automation/test_route_pr.py` (new) | T-RP-*, T-RA-*, T-CO-*, T-CID-*, T-EP-*, T-FS-*, T-HT-*, T-GH-*, T-REPLAY (§5) |
| 6 | `tests/automation/fixtures/pr2207_0227Z.json` (new) | §5.3 |
| 7 | `tests/automation/test_merge_authority_cli.py` | Add `route` and `bounce` to a new `_MUTATION_ARGVS`. Extend T1.7 (widening flags) and T1.4 (only `overseer` is accepted) to them. Add T-CLI-* (§5). `_ALL_ARGVS`, T1.1, T4.1, T4.2 and T4.7 keep the read-only set |
| 8 | `SCRIPTS-INDEX.md` | Regenerated with `scripts/framework/regen_all.sh` (two first-line changes; `github.py`'s first docstring line is unchanged) |
| 9 | `scripts/automation/lib/github.py` | §3.17: `list_issue_events`, `get_contents`, `list_check_suites_for_ref`. Additive; no existing function changes |
| 10 | `contract/OVERSIGHT-CONTRACT.md` | §3.15: the `pr-bounced` table row and JSON schema block only |

ADR §4's separate test files (`test_bounce_disputes.py`, `test_bounce_idempotency.py`,
`test_route_resolution.py`, `test_route_carry_veto.py`, `test_pr2207_replay.py`) are folded into file 5,
or deferred to S1b, so the slice stays at 10 files (the cap is 15). `correlation.py`, `codeowners.py`,
`tests/automation/test_github.py` and `.claude/agents/**` are **not** edited. In `contract/**`, only the
`pr-bounced` entry changes.

---

## 5. Tests mapped to acceptance criteria

### 5.1 `tests/automation/test_route_pr.py`

| ID | Test | Covers |
|---|---|---|
| T-RP-T | **Rule table:** one parametrized row per §3.8 row (28 rows), plus one **[AR4-1]** row (veto `NEEDS_START` with a rule-6c `NOOP` gives `actions == ("start-veto-window", "repair-finalize")`), plus two **[AR1-C2]** rows: a `PATH_PENDING_ESCALATION` block with `source_pr == pr` on a clean head reaches the rule-8 result it would have without the block (here `HOLD`, `collectors-incomplete`), and on an approved escalated head reaches rule 2's next row; a `PATH_HOLD` block with `source_pr == pr` still gives `LEGACY`. Each row asserts `(disposition, rule, trigger, reason)`, plus `actions` where a row sets them (rule 6c: `repair-finalize`). The S1b-input rows (path blocks, pending rulings, upheld, veto) are built directly as `RouteInputs` | ADR rule list; carry: rule-table test |
| T-RP-C | One `BOUNCE` per class (a)-(f): `PROCEDURAL`, `REQUIRED_CHECK`, `CHECK`, `MERITS`, `SCOPE`, `REVIEW_FINDING` | REQ-1 AC |
| T-RP-2 | A `MERITS` security finding with `worker_authored=True` gives `BOUNCE`. `RouteInputs` has no tier or surface field to set | REQ-2 AC (pure half) |
| T-RP-6c | Re-run with the same identities gives `NOOP`. A reworded slug with the same class and path gives `NOOP`. A new `check_run` on the same path gives `BOUNCE` (TD-D2) | REQ-12; slug stability |
| T-RP-6d | `epoch_bounce_count=2` with a new key gives `ESCALATE bounce-cap` | REQ-7(ii) |
| T-RP-6a | An `APPROVED` reviewer act plus a rejection gives `ESCALATE reviewer-conflict` | ESC-2 C, REQ-7(iii) |
| T-RP-7 | A valid decision alone gives `ESCALATE decision`. A decision plus a rejection gives `BOUNCE` (rejections first). A malformed decision gives `BOUNCE` | REQ-6, ESC-3 ordering |
| T-RP-P | **Property test:** `itertools.product` over `worker_authored × hold_on_head × blocks{(),hold,unknown,pending} × veto{4} × code_open{0,1} × llm_rejection{0,1,new/old} × decision{0,1} × escalation{none, each act kind} × collectors_complete × pending_rulings{0,1} × upheld{0,1} × epoch_count{0,1,2}`. **P1:** `PROCEED` ⇒ worker-authored ∧ no hold ∧ no block ∧ veto ∉ {OPEN, NEEDS_START} ∧ no open code finding ∧ collectors complete ∧ no pending ruling ∧ no upheld-unescalated dispute. P1 holds **unconditionally**, with or without an escalation (AR4-2: rule 2 now checks pending rulings and upheld disputes before its `PROCEED` row). **P2:** not worker-authored ⇒ `LEGACY`. **P3:** `BOUNCE` ⇒ count < cap ∧ `to_bounce` non-empty ∧ every identity is new. **P4:** deterministic. **P6:** `ESCALATE` ⇒ the trigger is in `ESCALATION_TRIGGERS`. **P7 [AR1-C1]:** `veto == NEEDS_START` ∧ disposition ∉ {`LEGACY`, `RULING_REQUIRED`, `BOUNCE`, `ESCALATE`} ⇒ `"start-veto-window"` ∈ `actions`, so no `HOLD_VETO` (or any other hold) leaves an unstarted window unstarted. **P8 [AR1-C2]:** adding a `PATH_PENDING_ESCALATION` block with `source_pr == pr` never changes the result. The grid gains `block source_pr ∈ {pr, other}` | carry: property test |
| T-RP-P5 | `RouteInputs` field names do not match `tier|surface|security|protected|codeowner` | REQ-2 by construction |
| T-RA-1 | Each trigger with a later approval gives `PROCEED`, and a later `CHANGES_REQUESTED` or `needs-ai` label gives `HUMAN_SENDBACK` | ADR S1 tests (AD-5a) |
| T-RA-2 | An approval before the escalation, then a re-approval after it, gives the latest act: `PROCEED` | AD-5a |
| T-RA-3 | Acts by a bot, the human-proxy, a non-CODEOWNER, or on another head give `None`, so `HOLD` | AD-5a |
| T-RA-4 | **Revocation:** two approvals after the escalation, the later one `DISMISSED`, give `DISMISSED`, so `HOLD` | codex revocation regression |
| T-RA-5 | Approved with an open `REQUIRED_CHECK` gives `HOLD`, never `BOUNCE` | AD-5a |
| T-RA-6 | A decision approval without an `Option:` line, or with an unknown label, gives `HOLD`. A valid label gives `PROCEED` | AD-5a |
| T-RA-7 | A tie on time is broken by id. A `COMMENTED` review is ignored. Label events are ignored when `since=None` | §3.9 |
| T-CO-1 | `_codeowners_humans_from_text` equals `requester_trust.codeowners_humans` on every `test_requester_trust.py` CODEOWNERS case (written to a temp tree for the latter) | ADR AD-5a parity |
| T-CO-2 | `resolve_reviewer_from_text(...).login` and `.note` equal `codeowners.resolve_human_reviewer` on each R1-R11 case in `test_pr_review_resolution.py`, including team-owned → `HUMAN_REVIEWER` | carry: teams resolve as in step 6 |
| T-CO-3 | A CODEOWNERS file edited on the head is ignored: `fetch_codeowners_text` is called with `base.sha` only (asserted on the mock) | AF-7 |
| T-CO-4 | A 404 on all three paths gives `None`. A 404 then a hit on `/CODEOWNERS` uses the second. A 5xx raises. No content raises | §3.10 |
| T-CID-1 | A worker PR with `worker-2171-…` and issue 2171 open or closed gives `issue-2171`. A second PR on the same issue (re-entry, no re-entry line) gives `issue-2171` | AF-1, REQUIREMENTS §4 |
| T-CID-2 | Each fallback reason gives `pr-<n>` with `warn`: a human author, a `User`-type login spoofing the worker name, a non-matching ref, a fork, a 404 issue, N being a PR | AD-3 |
| T-CID-3 | `issue_lookup` raising `GitHubError` propagates (no fallback) | fail-closed |
| T-EP-1 | **ARCH-ESC-1 (A):** two bounces, an escalation record, then a new bounce gives `epoch_bounce_count == 0`. With `EPOCH_RESETS_AT_ESCALATION` monkeypatched to `False` it is 2 | ARCH-ESC-1 one-line switch |
| T-EP-2 | A sibling merged by the overseer before this PR opened resets. One merged after this PR opened does not. One closed by the worker does not. One closed by the human-proxy resets | AD-3 epoch |
| T-EP-3 | An event with an unparseable time is counted. `since=None` equals today's count | §3.5 |
| T-FS-1 | Schema refusals: an unknown key (`key`, `origin`), a reserved class, a path not in the diff, a path with `:123`, a bad slug, a `check_run` not on the head, an off-repo `source_url`, more than 50 entries, an oversize file | AD-1 |
| T-FS-2 | Canonical keys: `./bin/hos-cron` gives `bin/hos-cron`; the NFC form is matched; the case is kept; the `CHECK` key format; duplicate keys deduplicated | AD-1 |
| T-HT-1 | `effective_head_time`: a future-dated committer date is capped by the `github-actions` suite's `created_at`. **A suite whose runs are all `queued` (`started_at: null`) still bounds it [AR1-C7].** No `github-actions` suite gives `None`. A non-Actions app's suite, or a suite for another `head_sha`, is ignored | TD-D6; carry: server-side ordering |
| T-GH-1 | `list_issue_events` and `list_check_suites_for_ref`: two pages concatenated in order; a non-list (or malformed `check_suites`) page raises; `max_pages` full pages raises rather than truncating. `get_contents`: 404 gives `None`, a directory (list) payload raises, `ref` and a quoted path appear in the request (`_run_gh` patched) | AR1-C5 |
| T-HT-2 | A hold posted after the push on a head with a forged future committer date gives `hold_on_head=True` and `LEGACY` | F8 |
| T-REPLAY | §5.3 | REQ-14 AC, issue AC 7 |

### 5.2 `tests/automation/test_bounce_gate.py` (additions)

| ID | Test | Covers |
|---|---|---|
| T-BG-1 | Legacy rendering: the heading `## PR bounced to the worker: 1 finding(s) on <head12>`, `### Specific failures`, `- [register-missing-role:security] Required sign-off missing: security`; no "procedural completeness"; no "How to respond" | VF-4, VF-5, AD-4 |
| T-BG-2 | The findings rendering parses with the worker-format regex `^- \[(?P<id>[0-9a-f]{12}-F\d+)\] \((?P<cls>[A-Z_]+)\) (?P<summary>.+)$`. Every finding appears once, with the ids in order | REQ-4 AC |
| T-BG-3 | Two calls on the same head with the same keys give one comment, one event, and a second result `skipped=True` | REQ-12 AC |
| T-BG-4 | A same head with one new key bounces, continuing `F<k+1>` | AD-5 rule 6(e) |
| T-BG-5 | Repair table: each of the **five** TD-D9 states, with the expected calls, **plus [CWE-841]** draft without `needs-ai` but with an `unlabeled` `needs-ai` event after `T` (no label added), and not draft with `needs-ai` and a `ready_for_review` event after `T` (not converted), each by the worker and separately by a human. A read failure in any state that needs the read raises before any write. Also includes **both-failed** (not draft, no `needs-ai`, no event after `T`: label and draft applied) and **deliberate-ready** (a `ready_for_review` or `unlabeled` `needs-ai` event after `T` by the worker, and separately by a human: nothing done). An events read that raises, or that hits `max_pages`, raises and changes nothing. A legacy event with no `comment_created_at` uses `timestamp` | TD-D9; codex second review |
| T-BG-6 | `head_sha=None`: the head is read before the post. A read failure posts nothing and writes no event | TD-D5 |
| T-BG-7 | The event carries `head_sha`, `findings[{id,class,key,origin,path}]`, `comment_id`, `comment_created_at`, `epoch_start`, and no `detail` | REQ-13, AD-7 |
| T-BG-8 | `findings` given together with `failures`, or `findings` without `head_sha`, raises `ValueError` before any I/O | §3.6 |
| T-BG-9 | Neither rendering contains `REQUEST CHANGES`, `Expected action` or `needs-human` | REQ-5 |
| T-BG-10 | **[AR1-C3]** A legacy `failures=["register-missing-role:security", "check-failing:tests"]` bounce on head H, then a findings-path bounce on H with the collector findings `PROCEDURAL:register-missing-role:security` and `REQUIRED_CHECK:check-failing:tests`, gives one comment and one event; the second call returns `skipped=True`. The reverse order also skips. An unknown legacy token stays `LEGACY` and does not match any collector key | AR1-C3, REQ-12 |
| existing | `test_second_bounce_increments_bounce_number` patches the head read to return two **different** heads, which keeps its meaning | regression |

### 5.3 The PR #2207 replay (`fixtures/pr2207_0227Z.json` and `T-REPLAY`)

**Fixture content.** The coder captures these with the authenticated read path (`scripts/automation/lib/github.py`)
and commits the trimmed JSON. A comment field `"_provenance"` names each source:
- `pr`: number 2207; `user` `{login: "hos-worker-hos[bot]", type: "Bot"}`; `head.sha`
  `d33c93ba7c79d12c184ee1eb8c32b4b6916a2768`; `head.ref` as captured (it must match `^worker-2171-`);
  `head.repo.full_name` and `base.repo.full_name` `thurlow-research/HumanOversightSystem`; `base.sha`
  `a05c7e363ba7fd68ff9be6620c8b120a6bf8fc3a` (the merge base; F12); `state: "open"`; `draft: false`;
  `changed_files: 4`; `commits` as captured; `created_at` as captured;
- `files`: the four F12 paths;
- `issue_2171`: `{number: 2171, state: <captured>}`, with no `pull_request` key;
- `check_runs`: the head's check runs as captured, trimmed to `{id, name, conclusion, started_at, app: {slug}}`.
  It must contain the `shellcheck` run;
- `check_suites` **[AR1-C7]**: the head's check suites as captured, trimmed to `{id, head_sha, created_at, app: {slug}}`;
- `required_checks_result`: `{bounce_required: false, failures: []}` (the captured required checks were
  not failing at 02:27Z), or as captured;
- `register_result`: `{bounce_required: false}`;
- `reviews`: `[]` and `comments`: `[]`, because the human's `CHANGES_REQUESTED` (04:20Z) and the relay
  (04:24Z) came after 02:27Z;
- `codeowners_base_text`: `git show a05c7e363:.github/CODEOWNERS`, verbatim;
- `findings_file`: `{"findings": [{"class": "CHECK", "check_run": "shellcheck", "rule": "SC1090", "path": "bin/hos-cron", "summary": "New shellcheck SC1090 at bin/hos-cron:1039: the identity-probe source \"$_rt\" lacks a # shellcheck source=/dev/null directive", "detail": "The next source of $_rt below already carries the directive; add the same one."}]}`.
  This is the overseer's finding from the 02:27Z record's summary;
- `audit_events`: `[]`.

**T-REPLAY** runs `cli.main(["route", "--app", "overseer", "--pr", "2207", "--step", "<captured or 1>", "--findings-file", <tmp>, "--repo", "thurlow-research/HumanOversightSystem"])`
with the github reads monkeypatched from the fixture, `HOS_BOT_LOGIN` set to the overseer handle, and
`post_comment`, `_run_gh` (label) and `_convert_pr_to_draft` captured. It asserts:
- exit 0; `disposition == "BOUNCE"`; `rule == "6e"`; `cid == "issue-2171"`;
- the posted body contains `[d33c93ba7c79-F1] (CHECK)` and `SC1090`, and does **not** contain
  `REQUEST CHANGES` or `needs-human`;
- the only label applied is `needs-ai`. **No** call to `requested_reviewers`, `/reviews` or any
  `needs-human` label is made (REQ-2, REQ-3);
- `touches_protected_surface(["bin/hos-cron"], repo_root=<repo>)` is `True`, which shows the protected
  status was present and did not route to the human;
- a second run with the event now on disk gives `NOOP` (rule 6c) and posts nothing (REQ-12).

### 5.4 `tests/automation/test_merge_authority_cli.py` (additions)

| ID | Test |
|---|---|
| T-CLI-1 | `route` and `bounce` reject `--app worker` and `--app human` (exit 2), and each widening flag (exit 2) |
| T-CLI-2 | `HOS_BOT_LOGIN` unset, or a non-overseer value, gives exit 1 `acting_identity_not_overseer` with no fetch (asserted with a `get_pull` that raises) |
| T-CLI-3 | Each §3.16 read-failure row gives exit 1, and nothing is posted (`post_comment` not called) |
| T-CLI-4 | Head pin: `get_pull` returns another sha on the second read, giving exit 1 `head_moved` and no post |
| T-CLI-5 | A non-worker PR gives `LEGACY`, with no `list_pull_files` call (an early return) |
| T-CLI-6 | `route` never emits `PROCEED` in S1a: a clean worker PR gives `HOLD`, `collectors-incomplete`, and `not_verified` contains the S1b notes |
| T-CLI-7 | `bounce`: clean, same-head, at-cap and bounced paths, with their payload keys |
| T-CLI-10 | **[codex second review]** `route` on an already-bounced head (rule 6c `NOOP`) whose earlier bounce left the PR not draft, without `needs-ai`, and with no events after `T`: exit 0, `disposition` `NOOP`, `needs-ai` added and the PR converted to draft, `finalize_repaired` listing both, no comment and no new `pr-bounced` event. The same setup with a later `ready_for_review` event does nothing. An events read that raises gives exit 1 and no write |
| T-CLI-8 | The documented payload keys are present for `route` and `bounce` |
| T-CLI-9 | **[AR1-C6]** One case per exit-1 row of §3.16 asserts `error_code` and `error_class`. `classify_github_error` gives transient for `RateLimitError`, `status_code=None` and 502, and deterministic for 404, 422 and a plain 403. Exit 0 and exit 2 records carry `error_class: null` |
| existing | T2.8: the `bounce-count` handler still calls `bounce_count(cid, repo_root=...)` with no `since` |

---

## 6. S1b — named, not built here

### 6.1 Files (target ≤ 12)

`scripts/automation/lib/merge_authority.py`; `scripts/automation/merge_authority_cli.py`;
`bootstrap/merge_authority.sh`; `scripts/automation/lib/github.py` (the compare and timeline reads,
ruled into `github.py` by architect round 1, Q2/C5); `tests/automation/test_bounce_disputes.py` (new);
`tests/automation/test_route_holds.py` (new); `tests/automation/test_route_carry_veto.py` (new);
`tests/automation/test_merge_guard.py` (new); `tests/automation/test_merge_authority_cli.py`;
`contract/OVERSIGHT-CONTRACT.md` (§6a: the `human-required` extension and every new S1b event; `pr-bounced` already landed in S1a, AR1-C4); `SCRIPTS-INDEX.md`.

### 6.2 Scope

- `head-observed` and `paths[]` on every per-head event, from `GET /compare` with paging and truncation
  handling;
- `path_blocks`, `path-hold`, `path-block-noted`, the unknown-scope global block, `PATH_BLOCK_EXCLUDE`;
- `/hos release-hold`;
- `parse_dispute`, `scan_disputes`, `dispute-refused` with its cap, the fenced reason, `dispute-ruling`
  (evidence binding, `--carry`), `ruling-pending` and `ruling-defaulted`;
- the veto window (`withdraw-visible-since`, `WITHDRAW_VETO_MIN`);
- `route-proceed`, `merge-guard` (both modes), `human-ruled`, `classify_merge_failure`,
  `merge-failed` and `merge-attempt-transient`;
- `record-escalation` (`human-required` with `cid`, `head_sha`, `trigger`, `merge_base_sha`,
  `escalation_created_at`, `options`), and `disputes`;
- the validator-artifact collector, and `collectors_complete` becoming true;
- Contract §6a for the S1b events.

### 6.3 Rulings that gate S1b, and the obligations S1a hands it

| Ruling or item | Effect on S1b |
|---|---|
| **ESC-4 (unruled)** | (A) builds sticky, path-keyed, cross-issue holds, `/hos release-hold`, the non-worker `merge-guard` mode and the 30-minute veto window. (B) drops the cross-issue reach of a hold, so `path_blocks` keys only this PR's paths. **S1b must not be coded until ESC-4 is ruled.** The `Block` interface (§3.2) is the same under both |
| **ARCH-ESC-2** | (B) adds one refusal condition to `dispute-ruling` for `touches_security_surface` findings. `route_pr` is unchanged under both |
| ESC-3 | As in S1a (§7) |
| **`path_blocks` source attribution [AR1-C2]** | Every `Block` that S1b builds carries the `source_pr` it was derived from: the held PR for a `PATH_HOLD`, and the escalated PR for a `PATH_PENDING_ESCALATION`. `UNKNOWN_SCOPE` carries the PR whose hold could not be scoped. `route_pr` relies on `source_pr` to ignore a PR's own pending escalation (§3.8), so a block with a missing or wrong `source_pr` is a defect. S1b tests that an escalated PR is not blocked by its own escalation, and that a sibling with intersecting paths is |
| **Rule-2 precedence defect (found by the risk-assessor, prompt-fidelity and code review on this TD) — RULED, architect round 4, option (1)** | Rule 2's approved-`PROCEED` row preceded rule 3 (`pending_rulings`) and rule 5 (`upheld_unescalated`), so an approved escalated head with a pending ruling or an upheld dispute returned `PROCEED`, which contradicted P1. **Ruling:** the architect chose option (1) as a technical call. The two checks become rule-2 approved-branch rows (§3.8), after collectors-incomplete and decision-option-missing and before the veto and pending-block rows. P1 is unconditional again. Rationale: it keeps P1 unconditional, and it moves only in the delay direction. **It lands in S1a** (unreachable there, but pinned by T-RP-T and T-RP-P). The product consequence goes to the human (Human Review Required) and **must be cleared before S1b populates these inputs**. Round 3's approval of TD-D10 and P1 is superseded **for rule 2 only**. The S1a code review must re-check `route_pr` rule 2 and T-RP-P after this delta |
| **Closed sibling without a `closed` event** | Now exit 1 per §3.5 (`epoch_sibling_missing`, deterministic; code-review SHOULD_FIX 5, being implemented in S1a). S1b inherits the rule unchanged |
| **Base-tip CODEOWNERS (security SF3, CWE-367)** | `pr.base.sha` can lag the base-branch tip, so a CODEOWNERS removal made after the PR was created is not seen, and a revoked owner could still resolve as the reviewer. **Before `PROCEED` is reachable** (S1b, when `collectors_complete` can be true), S1b reads CODEOWNERS at the current base-branch tip, or fails closed (exit 1, deterministic) unless `base.sha` equals that tip |
| **cid issue binding (security SF4, CWE-639)** | `bounce_cid` trusts the issue number in the worker's own branch name (R-4 bounds the impact). S2 may additionally check N against the PR body or the PR's linked closing reference, and fall back to `pr-<n>` with a WARN on a mismatch |
| **Overseer identity check (security SF5)** | TD-D8's check trusts the `HOS_BOT_LOGIN` environment variable, not the token's identity. It is a convention guard. If a later slice relies on it as a security control, verify the identity from the token itself (`GET /app` or `GET /installation`) instead |
| **The overseer's closures reset the budget (security SF6)** | The overseer closing a worker PR counts as non-worker and resets the epoch (§3.5; intended). S2 must ensure the overseer never auto-closes worker PRs in a loop, which would reset the budget indefinitely |
| **Security re-assessment (security)** | Security review is re-run at S1b and at S2, once `PROCEED` is reachable from the CLI. S1a's review rests on TD-D4 (no `PROCEED`) |
| **Duplicate bounce comment on POST retry (reliability 1)** | `post_comment` uses `_run_gh`'s default `retries=3`, so a POST that times out after GitHub accepted it can post a duplicate bounce comment. Consider `retries=0` on that POST (the #1811 pattern), with a read-back dedup |
| **No aggregate deadline in the epoch read (reliability 2)** | The epoch computation can make up to 50 siblings × 2 reads, with no overall deadline. It relies on the optional `HOS_CRON_MAX_SECONDS` (#1146). S1b adds an aggregate deadline (exit 1, transient), or lowers `_EPOCH_MAX_SIBLING_PRS` |
| **Fallback WARN not pinned (ops 2)** | No test pins the stderr `WARN:` line or the `not_verified` entry on a `pr-<n>` fallback (§3.13 step 3). S1b adds one per fallback reason |
| **Exit-1 paths write no audit event (ops 3)** | By design, S1a writes nothing on exit 1. S2's retry counter logs those attempts as audited events; see the R2-2 hand-off in §3.16 |
| **Dedup key vs. identity (code-review NIT)** | `record_pr_bounce`'s same-head skip compares **keys** (§3.6 step 3), while `route_pr` rule 6(c) and `bounce` filter by **identity** (TD-D2). For LLM findings, a reworded slug is the same identity but a different key. `route` never passes such a finding (6(c) returns `NOOP` first), so the two agree in practice. S1b either aligns the skip on identity or documents the difference |
| **Ready-for-review check in the "not draft, `needs-ai` present" repair state (security delta review of be2f3c69f, SHOULD_FIX low) — RESOLVED in S1a (codex second review, CWE-841)** | Both single-missing states now check the events after `T` before writing (TD-D9 table). Nothing is left for S1b |
| **S2 obligation: serialize the bounce read-then-write (codex second review, CWE-362)** | `record_pr_bounce` and `repair_bounce_finalize` read the audit log and the PR, then write. That sequence is not serialized. The per-role cron overlap lock stops two cron cycles from overlapping, but nothing stops a concurrent interactive caller from producing a double bounce or a double repair. **#2227 must land before S2 makes `route` and `bounce` the overseer's live path** |
| Interface | S1b populates `blocks`, `pending_rulings`, `upheld_unescalated`, `withdrawn_on_head` and `veto` in `RouteInputs`, and removes them from `s1b_inputs_stubbed`. `route_pr` is unchanged, except where a ruling requires otherwise |
| **R-7 (risk-assessor)** | A withdraw drops only the exact **finding id** it ruled on. `withdrawn_on_head` holds ids, never class+path, so withdrawing F1 cannot suppress a different finding that shares its class and path |
| **Held head (security)** | The held head is chosen by server-set order only: `effective_head_time`-style bounds and `head_ref_force_pushed.created_at`. Timeline `committed` dates (commit metadata) are never used |
| **`head-observed` first (code review)** | For worker PRs, `head-observed` is written immediately after `worker_authored` is known (§3.13 step 4) and before rule 1's hold evaluation |
| **Compare paging and truncation (risk-assessor)** | A comparison with `files` of length ≥ 300, or a `status`/`total_commits` that does not match, is a truncation. That is exit 1, with no event |
| **Bounded compare failures (code review)** | After 3 consecutive cycles of compare failure on one `(pr, head)`, recorded as `compare-failed {pr, head_sha, n}`, record `head-observed` with `paths: null`. Under the S1b rules a hold on that head is then unknown-scope (fail-closed) instead of the PR stalling silently |
| **The unknown-scope comment names `HUMAN_REVIEWER` (code review)** | The one-time note on an unknown-scope block names `HUMAN_REVIEWER` and the PR where the release must happen |
| **Lost audit log availability (risk-assessor, #1803)** | S1b must decide, and state, what an **absent** `audit/log/` means. ADR R-3 makes an unreadable stream "held". An absent one would make every worker PR globally blocked under the unknown-scope rule. S1b proposes an explicit `audit-log-absent` HOLD with a one-time note naming `HUMAN_REVIEWER`, never a silent stall |
| **Pin `/hos release-hold` (security)** | Exact-match tests covering a bot, the human-proxy, another human, an edited comment, and a second line |
| **Degraded required-check read** | `collectors_complete = False` (§3.11) |
| **Cutover** | Worker PRs with pre-S1b `pr-bounced` events that carry no `paths[]`: a hold on such a PR is unknown-scope. S1b states whether that is accepted or seeded from `head-observed` at first sight |

---

## 7. Rulings this slice assumes

| Ruling | Status | What S1a assumes | Where it lives | Cost if ruled otherwise |
|---|---|---|---|---|
| ESC-3 | open (rec A) | **(A):** non-worker PRs stay `LEGACY` | `route_pr` rule 1, first row; `bounce` `non-worker-pr` | (B) or (C): one rule-1 row changes, plus `bounce`'s early return |
| ARCH-ESC-1 | open (rec A) | **(A):** the epoch also restarts at each escalation | `EPOCH_RESETS_AT_ESCALATION = True` | (B): set it to `False`; T-EP-1 already covers both |
| ESC-2 | open (rec C) | **(C):** an approval on a head plus a rejection gives `reviewer-conflict` | rule 6a | (A) or (B): one row |
| ARCH-ESC-2 | open (no rec) | nothing; S1a has no `dispute-ruling` | — | S1b only |
| ESC-4 | **unruled** (PR #2223 approved without a textual ruling) | nothing; no hold stickiness, release or veto is built | `Block` and `VetoState` interfaces only | S1b only |
| ESC-1 | open (rec A) | nothing (S2) | — | — |
| `BOUNCE_CAP` | fixed by REQUIREMENTS §3 | 2 | unchanged | — |

ESC-3, ARCH-ESC-1 and ESC-2 gate S1a's **merge**, not its build. The PR's `## Human Review Required`
block must list them.

---

## 8. Disposition of the PR #2223 carry list

| Source | Item | Disposition |
|---|---|---|
| security | identify the held head by server-side order only | **S1b** (§6.3). S1a supplies `effective_head_time` and already uses it for the non-sticky #902 check (TD-D6, T-HT-*) |
| security | pin `/hos release-hold` in tests | **S1b** |
| risk-assessor | availability of the unknown-scope global block when the audit log is lost | **S1b** (§6.3). S1a's lost-log effect is only a fresh budget (§3.5) |
| risk-assessor | compare-endpoint paging and truncation | **S1b**. S1a uses `pulls/files`, cross-checked against `changed_files` (§3.12) |
| risk-assessor | R-7 key granularity | **S1a:** TD-D2 (finer `CHECK` identity). **S1b:** withdraw by exact id (§6.3) |
| risk-assessor | rule-table test and property test | **S1a:** T-RP-T, T-RP-P |
| risk-assessor | CODEOWNERS teams resolve as in step 6 | **S1a:** TD-D3, T-CO-2 |
| code review | write `head-observed` before rule 1 | **S1b** (§6.3), with its position fixed at §3.13 step 4 |
| code review | the unknown-scope hold comment names `HUMAN_REVIEWER` | **S1b** |
| code review | bound repeated compare failures | **S1b** (§6.3) |

---

## 9. Rulings of architect round 1 [AR1-C9]

Source: `.claudetmp/design/architect-2209-s1-2026-10-31T060000Z.md` (verdict CHANGES_REQUIRED, C1-C9).

| # | Item | Ruling | Amendment text, or how it is folded in |
|---|---|---|---|
| 1 | TD-D1: structured parts in the findings file; the CLI builds `key` | **approved, architect round 1** | As written in §2 and §3.3 |
| 2 | TD-D2: finer `CHECK` identity | **approved, architect round 1** | Cited as "ADR-2209 AD-5 slug-stability, refined for CHECK by TD-D2 (architect round 1)" |
| 3 | TD-D3: step 6's resolution on base-ref text, with a humans-set drift guard | **approved, architect round 1, as an ADR-2209 AD-5a amendment; wording confirmed in round 2 (R2-1)** | The architect's verbatim amendment is quoted in §2 TD-D3: the resolver is `resolve_human_reviewer`'s algorithm on base-SHA text, with the three lookup locations in order; `_codeowners_humans_from_text` is byte-equivalent to `requester_trust.codeowners_humans` and serves as the consistency check; drift is exit 1 `codeowners_resolution_drift`, deterministic |
| 4 | TD-D4: no `PROCEED` from the S1a CLI | **approved, architect round 1** (Q1) | As written |
| 5 | TD-D5: `record_pr_bounce` reads the head when not given | **approved, architect round 1, with C8** | Residual R-TD5 (head race, safe direction) added under TD-D5 |
| 6 | TD-D6: server-bounded head time for `route`'s #902 check | **approved, architect round 1, with C7** | Bounded by the `github-actions` check suite's `created_at` (option (a)), read with `github.list_check_suites_for_ref`. The queued-run case is in T-HT-1. R-TD6 does not arise. The same flaw elsewhere goes to a separate issue (Q3) |
| 7 | TD-D7: `--step` on `route` and `bounce` | **approved, architect round 1** | As written |
| 8 | TD-D8: overseer-only mutation subcommands | **approved, architect round 1** | As written |
| 9 | TD-D9: same-head skip repairs an unfinished finalize | **approved, architect round 1** | As written |
| 10 | TD-D10: rule 2's `PROCEED` requires every blocker absent | **approved, architect round 1, with C1 and C2** | C1: every rule-2 result carries `start-veto-window` when the veto is `NEEDS_START`; the approval branch is `HOLD_VETO` with the action when the veto is `NEEDS_START`, without it when `OPEN`; property P7. C2: `RouteInputs.pr`; a PR's own `PATH_PENDING_ESCALATION` block is ignored and its `PATH_HOLD` is not; property P8; the S1b `source_pr` obligation in §6.3. **Superseded for rule 2 only by architect round 4 (R4-2, Q5 option (1)):** two new approved-branch rows for pending rulings and upheld disputes |
| 11 | C3: legacy-token identity at cutover | **required, architect round 1** | `legacy_token_finding` (§3.6) maps `register-*` to `PROCEDURAL:<token>` and `check-failing:<n>` to `REQUIRED_CHECK:check-failing:<n>`; T-BG-10 |
| 12 | C4: the contract's `pr-bounced` entry lands in S1a | **required, architect round 1** | §3.15. File 10 in §4 |
| 13 | C5: generic reads in `github.py` | **required, architect round 1** (Q2) | §3.17: `list_issue_events`, `get_contents`, `list_check_suites_for_ref`. `fetch_issue_events` is removed from `merge_authority.py`. `fetch_codeowners_text` stays there, over `get_contents`. S1b's compare and timeline reads also go in `github.py`. Tests are in `test_route_pr.py` (T-GH-1) |
| 14 | C6: `error_class` on every exit 1 | **required, architect round 1** | §3.12 and §3.16 (each row assigned); the S2 hand-off: a deterministic error is surfaced as one escalation note per `(pr, head, error_code)`, never re-skipped silently; T-CLI-9 |
| 14a | R2-2, R2-3, R2-4: the S2 hand-off | **required, architect round 2; three strikes approved** | §3.16 S2 hand-off: three strikes counted from an audited S2 event `{pr, head_sha, error_code}`, reset by an exit-0 `route` or a new head; #1215 suppresses duplicate notes only, never the `route` run; the overseer regenerates findings-file errors in the same cycle and surfaces them only on a second consecutive cycle |
| 14b | Nit: section order | **architect round 2** | §3.17 (`github.py`) now precedes §3.18 (the wrapper) |
| 19 | TD-D9: the ambiguous "ready, unlabeled" state, and route `NOOP` never repairing | **required, codex second review (CWE-703, medium, blocking)** | TD-D9 tells deliberate from both-failed using server-side issue events after `T`, with any actor counting as deliberate. A failed or truncated read is exit 1. Rule 6c's `NOOP` carries `repair-finalize`, and `route` runs `repair_bounce_finalize`. T-BG-5 now covers five states; T-CLI-10 added |
| 20 | R4-1 actions accumulate; R4-2 Q5 option (1) | **required, architect round 4** (TD-D9 amendment approved in substance) | §3.2 and §3.8: `actions` is the ordered concatenation of every attached action, rule 4's first, and 6c appends `repair-finalize`. Rule 2 gains the pending-ruling and upheld rows. P1 is unconditional. A new T-RP-T row. §6.3 and §11 Q5 are marked ruled. The product consequence is in Human Review Required. Residual R-TD9 (clock skew) is stated |
| 21 | Single-missing repair states undo deliberate acts (CWE-841); bounce read-then-write is not serialized (CWE-362) | **required, codex final second review** | CWE-841: TD-D9's two single-missing states now check `unlabeled` or `ready_for_review` events after `T` (any actor) before writing, and the read raises before any write. R-TD9b and its §6.3 row are resolved in S1a; T-BG-5 extended. CWE-362: a §6.3 S2 obligation that #2227 lands before S2 goes live |
| 15 | Q3: the forged-date flaw in `hold-directive` and the matrix | **separate issue, architect round 1** | Filed as #2226. This TD references it only as a follow-up (§2 TD-D6, §11) |
| 16 | Q4: soft size limits as code-collected `SCOPE` | **approved, architect round 1; not a product question** | No pm-agent routing |
| 17 | Landing order S1a → S1b → S2 → S3 | **binding, architect round 1** | §1 |
| 18 | ADR §4's S1 test files consolidated | (unchanged) | §4. Contract §6a now splits: the `pr-bounced` entry in S1a (C4), the rest in S1b |

---

## 10. Startup gap and affected sign-offs

- **Startup gap: yes (AF-1),** as the ADR recorded. #1580's cap assumed a stable cid that nothing
  produced. S1a's `bounce_cid` is the fix. A `startup-artifact-gap` issue should be annotated (not filed
  here). This document is new and does not itself correct an earlier technical design.
- **Sign-offs:** #1580's 4c sign-offs (their cap claim was never true) and SPEC-378's `pr-bounced` schema
  sign-offs (S1a adds fields) need re-review against S1a, as the ADR states. TD-D6 touches no existing
  sign-off, because `hold-directive` and the matrix are unchanged. C4's contract edit is the
  SPEC-378 `pr-bounced` schema change already named here. #2174's sign-offs stand: no file
  overlaps.

---

## 11. Open items after architect round 1

- **AD-5a amendment wording:** confirmed in architect round 2 (R2-1). It is quoted verbatim under TD-D3.
- **Follow-up issue (already filed as #2226, per the Q3 ruling):** the forged-committer-date flaw in the
  `hold-directive` subcommand and in `decide_merge_authority`'s #902 input (F8). It is out of #2209's
  scope (REQUIREMENTS §3).
- Q1, Q2 and Q4 are resolved (§9 rows 4, 13 and 16).
- **Q5: ruled, architect round 4, option (1)** (a technical call). Pending rulings and upheld disputes are checked inside rule 2 before its `PROCEED` row, and P1 is unconditional. Rationale: P1 stays unconditional, and the change moves only in the delay direction. The product consequence is routed to the human (below) and must be cleared before S1b populates the inputs.

---

```
RISK: HIGH
CONFIDENCE: HIGH on F1-F12 (each re-read at 96d7ae66f); MEDIUM on TD-D6's check-suite bound (it relies on
            GitHub creating the github-actions suite server-side at push time; the worker App cannot
            create or alter a github-actions suite)
BLAST RADIUS: today — the bounce comment text, plus one extra PR read and a same-head skip in
              record_pr_bounce. After S2 — the routing of every worker-PR rejection
CHANGE CLASSIFICATION: additive (a new design that refines ADR-2209's slice plan; round 2 folds in the
              architect's C1-C9 and round 3 folds in R2-1..R2-4; one AD-5a amendment (TD-D3), approved in
              round 1, wording confirmed in round 2)
```

## Human Review Required

S1a touches protected surfaces (`merge_authority.py`, `bootstrap/merge_authority.sh`). Its merge needs
your ruling on **ESC-3** (S1a builds option A), **ARCH-ESC-1** (option A, a one-constant switch) and
**ESC-2** (option C, one rule row). **ESC-4** is still unruled, and S1b must not be coded until you
rule on it.

**Product consequence of the architect's round-4 ruling (Q5 option (1)), which needs your clearance
before S1b populates disputes.** Your approval on an escalated head will no longer clear a dispute the
worker raised **after** the escalation. The overseer must rule on that dispute first, and if it upholds
it, you may be asked a second time on the same head. The change is in S1a, where it is unreachable. It
takes effect once S1b feeds disputes into `route`.
