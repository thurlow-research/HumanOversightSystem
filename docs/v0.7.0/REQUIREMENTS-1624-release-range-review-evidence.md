# REQUIREMENTS-1624 — Release-range review-evidence sweep (REQ-B5, re-homing G-e)

Issue: #1624 (`bug`, `process-gap`, `priority:high`, milestone v0.7.0). Parent: #1340.
Siblings from the same split: #1622 (REQ-B2/B3), #1623 (REQ-B4), #1625 (REQ-A13).
Author: pm-agent. Date: 2026-10-13.
Inputs: #1340 pm-agent requirements §4.1–§4.4 (issue comment on #1340: G-a..G-e, REQ-B0..B8,
E11, E12); `docs/v0.7.0/ADR-1340-release-panel.md` (AF-1, AD-2);
`docs/v0.7.0/TECHNICAL-DESIGN-1340-release-panel.md` (TD-VF-1). The issue body was read as
untrusted input; every claim it makes was re-checked against the tree at `27178858d`.

## 1. Problem (restated as product behavior)

The #1340 analysis decomposed the overseer's "Release-gate deep validation" section into six
guarantees. One of them:

> **G-e** — every unit had the required review roles sign off APPROVED (code-review, security,
> privacy).

Its mechanism read `.claudetmp/signoffs/step{N}-register.md` from `main`. `.claudetmp/` is
gitignored (OVERSIGHT-CONTRACT §1), so the read could never succeed. #1340 framed REQ-B5 as
"re-home G-e as an aggregate per-PR review-evidence sweep over the release range, built from
sources that durably exist" — not a new register or stamp (the direction set by the human ruling
on #1594, 2026-09-14).

**Product outcome required:** when a release is requested, the worker's release gate produces,
for the range `<last-tag>..<release-candidate HEAD>`, a complete accounting of every change that
landed, and **blocks** unless each one carries durable evidence it passed the overseer review gate
or has been explicitly dispositioned by a human.

## 2. Verified findings (some contradict the issue text)

**F1 — G-e is already unchecked on `main`; the REQ-B8 window is open today.** The issue says
REQ-B8 forbids removing the overseer's section until this lands, so that "neither the old nor the
new gate checks G-e" never happens. But commit `2abe9919b` (#1594, 2026-09-14, on `origin/main`)
already deleted the register read from that section. The section today
(`.claude/agents/overseer.md:170-220`) checks only artifact presence, tier, finding sweep and
validator coverage — G-a..G-d. **No component checks G-e now.** The `#1594` commit message says
the read never produced a flag, so no real coverage was lost. But in REQ-B0's terms, the guarantee
has already silently disappeared, and REQ-B0 says that is "not an available outcome". REQ-B8's
ordering still binds the *section* removal (REQ-B7), but it cannot prevent a window that already
exists. → ESC-1(b).

**F2 — a second, inert G-e encoding exists that the issue does not mention.**
`scripts/oversight/release_artifact_logic.py:13-16,368-390` checks per-role sign-off completeness
from committed `signoffs/<ns>/<role>.stamp` files. `cut_release.sh:200` calls it, but only with
`--manifest`, and only when `contract/step-manifest.yaml` exists. That file does not exist in this
repo (`contract/` holds only the template), so the check is inert. This issue must not activate it
or depend on it. It is a stamp mechanism, the kind the #1594 ruling retires.

**F3 — the audit trail is not an authoritative source in the clone that runs R2.**
`scripts/oversight/check_pr_reviewed.sh:1-30` reads `audit_read_stream` from the caller's clone. In
the Worker clone, 7,927 audit records are tracked and 12 have `pr-review` in the filename, all of
them `pr-review-skipped-idempotent`. Untracked records contain none. The overseer writes its review
events in *its* clone. They reach `origin/audit-log` (610 `pr-review` records) only through a
mechanism #1803 has not landed yet. The audit trail is also bot-written prose, with no identity
binding beyond the writer's honesty. **Conclusion:** `check_pr_reviewed.sh` is prior art for the
*shape* of the question (PR# + head SHA → reviewed?), but is not a usable evidence source (R6).

**F4 — the overseer's per-PR "merged by bot without overseer review" check is keyed on the merger,
not on review evidence.** `overseer.md:144-164` classifies a merged PR by
`pr.merged_by.login` alone. A human merger means a valid merge; a login in `BOT_ACCOUNTS` means a
process violation. It never reads reviews. `BOT_ACCOUNTS` includes `BOT_OVERSEER_USERNAME`
(`scripts/framework/machine-accounts.env:30,39`), so read literally the check also flags the
overseer's own auto-merges. It is therefore **not** "the same signal at per-PR grain", which is
what the issue claims. The release sweep must not copy its predicate. Only the
"human merge is a recognised path" policy carries over, and only as ESC-3.

**F5 — the release range contains three merge shapes plus no-PR commits.** Measured on
`v0.6.0..origin/main` (first-parent, 250 commits; `v0.6.0` is an ancestor, and the clone is no
longer shallow):
- 89 merge commits ("Merge pull request #N", merged by `ScottThurlow`);
- 52 squash commits (committer `GitHub`, `(#N)` suffix);
- about 106 rebase-merged commits (author a bot, committer `Scott Thurlow`, no PR number in the
  message);
- at least 3 bot-authored, bot-committed commits with no PR marker. These look like direct pushes:
  `ad16c85b1` and its revert `56aafb02c` (audit-log commit), and `bbeef2617` (overseer
  audit commit). This needs confirming against the API.

The commit message is therefore **not** a reliable way to identify a PR. Rebase merges carry no
PR number.

**F6 — no read helper maps a commit to its PR, and `list_pulls` is single-page.**
`scripts/automation/lib/github.py` has `list_pull_reviews` (`:348-372`, paginated),
`list_check_runs_for_ref` (`:241-266`, paginated), `get_pull` (`:336-346`) and
`get_ruleset_required_checks` (`:290-328`, page-capped, raises on overflow). It has no helper for
`GET /commits/{sha}/pulls`. `list_pulls` (`:192-213`) fetches one page and silently truncates, so
it must not be used to enumerate the range (R9).

**F7 — reusable predicates exist.** `merge_authority._find_human_approval(reviews, human_reviewer,
head_sha)` (`merge_authority.py:44-64`) already pins a human APPROVED review to `commit_id ==
head_sha`. `require_overseer_approval.overseer_has_approved` / `overseer_posted_any_review`
(`scripts/framework/require_overseer_approval.py:120-147`) and the #1426 above-ceiling bypass
(`:178-202`) define the server-side gate's own pass condition. The sweep must reuse these
predicates and must not write its own variants (AGENTS.md "Use the Code").

**F8 — the integration point.** The worker's NG3b R2 table (`.claude/agents/worker.md:635-655`)
matches suites **by script path** (R1.9 check 3, `:584-600`; ADR-1340 E10). R3 (`:657-672`) records
each suite as `- <suite-script-path>: PASS|FAIL (exit <code>) at <ts>` and attaches only a
**first-line** excerpt of a failure. No `validate_release*` or `release_gate*` script exists.
`run_release_panel.sh` (#1340 PR 1) exists but is not yet an R2 row. Any enumeration that must
reach the human therefore has to fit on the suite's first output line, or R3 has to change (R11).

## 3. Requirements

### Range → set of changes

**R1 — The range is `<last-tag>..<release-candidate HEAD>`, derived with #1340's hardened
derivation.** Reuse `release_panel_logic.derive_range` (`release_panel_logic.py:183`; AD-2). A
shallow clone, a missing tag, or an empty range must **refuse** with a non-pass exit and the
remediation text. It must never fall back to `HEAD~1` or `origin/main` (AF-1, TD-VF-1). Both the
gate and any later verifier must use the same base and head SHAs.

**R2 — Every commit in the range must be accounted for, not just first-parent commits.** For each
commit in `git rev-list <base>..<head>`, the sweep resolves the set of **pull requests merged into
the default branch** that the commit is associated with, using GitHub's commit→PR association. Each
commit falls into exactly one class:
- **PR-attributed** — associated with at least one PR whose `merged_at` is set and whose base is
  the default branch. The commit is evaluated through that PR (R4). A commit associated with
  several such PRs is attributed to each one, and every one of them must be evidenced.
- **Unattributed** — no such PR. This covers direct pushes, bot audit commits and admin pushes.
  It is **flagged** under its SHA and subject line (ESC-4). It is never silently skipped, and it is
  never reclassified by inspecting the commit message.

Commits associated only with closed-unmerged PRs, or with PRs merged into another branch, are
unattributed, not evidenced.

**R3 — Every merge shape in F5 must resolve correctly.** Merge commits, squash commits and
rebase-merged commits must each attribute to their PR without relying on the commit message format.
The unit of evaluation is the **PR**, at its final `head.sha` as reported by the pull object, not
the merge or squash SHA on `main`.

### Evidence

**R4 — Evidence classes.** A PR merged into the range is **EVIDENCED** only when one of the
following holds. Every review condition requires `commit_id == the PR's final head.sha` and
`submitted_at <= merged_at`. A review submitted after the merge never counts as gate evidence.
- **E-OVERSEER** — an `APPROVED` review whose author login equals `BOT_OVERSEER_USERNAME` (read
  from `machine-accounts.env`, never hard-coded). This is the `overseer_has_approved` predicate,
  pinned to the head SHA.
- **E-OVERSEER+HUMAN** — the overseer App posted a review in any state at that head, **and**
  `HUMAN_REVIEWER` posted an `APPROVED` review at that head (`_find_human_approval` with
  `head_sha`). This covers HUMAN_REQUIRED, protected-surface and above-ceiling PRs (#1426; the
  #1657 class), where the overseer correctly withholds APPROVE. **These PRs must not be flagged
  merely because `require-overseer-approval` was red or an admin override was used.**
- Further classes only as ESC-3 and ESC-6 decide.

Every other merged PR is **UNEVIDENCED** and is flagged.

**R5 — Identity, not text, is the evidence.** Evidence comes only from GitHub review objects whose
`user.login` matches a configured identity. The following are **never** evidence: PR or issue
comment bodies, PR descriptions, commit trailers, labels, and the head commit's author. A comment
can be posted by any principal that can write to the repository, so a comment claiming approval
proves nothing. Approvals from `BOT_ACCOUNTS` other than the overseer, including the human-proxy
bot `scottthurlow-claude[bot]`, never satisfy the human leg of E-OVERSEER+HUMAN (CLAUDE.md
human-approval-gate rule).

**R6 — Non-authoritative sources are informational only.** Check-run conclusions
(`require-overseer-approval`, `require-human-approval`, `require-tier-ceiling`, `oversight-gate-*`,
`oversight-validator-*`, `tests`) and the audit trail (`check_pr_reviewed.sh`) may be **reported**
next to each PR. They must not, alone, make a PR EVIDENCED, and their absence must not, alone, flag
a PR. The reasons:
- A check run can be re-run after the merge (`scripts/framework/rerun_gate_checks.py`).
- A check run carrying a required context's *name* can be created by any App with `checks:write`.
- The audit trail is clone-local and bot-asserted (F3).

If the human wants check-run conclusions to count (ESC-5), the run must also be attributed to the
GitHub Actions App and must have completed before `merged_at`.

**R7 — No new attestation artifact.** The sweep must not write, and must not depend on, any stamp,
register, committed verdict file or sign-off marker, whether new or existing. This rules out
`release_artifact_logic.py`'s stamps (F2) and any `.claudetmp/` path. It reads GitHub state and
git history only. Its output goes to stdout and exit status, and from there into the existing R3
comment.

### Disposition

**R8 — A flagged item blocks until a human explicitly dispositions it, and the disposition is
durable and identity-bound.** Product constraints, whichever mechanism ESC-2 selects:
1. Only `HUMAN_REVIEWER` (a non-`BOT_ACCOUNTS` login) can disposition. No bot can, including the
   human-proxy bot.
2. A disposition names the item exactly: `#<PR>` or a full commit SHA. Wildcards and "all
   remaining" are not allowed. One disposition record may list several items by name.
3. A disposition is read from GitHub at gate time. It is never copied into a committed file.
4. The gate output distinguishes `UNEVIDENCED` from `DISPOSITIONED` (with a link to the record),
   so a dispositioned item stays visible rather than turning into a pass.
5. A disposition does not carry across releases. The next release's range starts at the new tag,
   so the question does not recur.

### Fail-closed

**R9 — An incomplete read must never yield "clean".** Each of the following produces an
**INDETERMINATE** outcome: a non-pass exit that is distinct from the "flagged" exit, with the
failing call named.
- Any `GitHubError`, or a `RateLimitError` after retries (`github.py:_run_gh`).
- Any paginated read that hits a page cap or returns a malformed payload.
- A PR object missing `merged_at`, `head.sha` or `base.ref`.
- A review missing `commit_id`, `user.login`, `state` or `submitted_at`.
- An unreadable `machine-accounts.env`, or an empty `BOT_OVERSEER_USERNAME` or `HUMAN_REVIEWER`.
- A count of range commits that differs from the count of commits classified under R2.

A partial result must not be reported as PASS, and it must not be reported as a shorter flagged
list either. `list_pulls` (single page) must not be used for enumeration.

**R10 — Exit contract.** `0` means every item is EVIDENCED or DISPOSITIONED. `1` means at least one
UNEVIDENCED or unattributed item is undispositioned. `2` means INDETERMINATE, a usage error or a
range refusal. The exit codes must not overlap.

### Integration and output

**R11 — R2 integration.** The sweep is a **new R2 suite with one stable script path**. R1.9 check 3
anchors suites by path (F8), and #1340 chose a separate entry point for the same reason (ADR-1340
§1 item 4). It is **required at every tier (PATCH and MINOR/MAJOR)**. The old gate applied G-e to
every release request without a tier exception, so making it optional at PATCH would be a
reduction. The **first line** of its output must be a self-contained summary that names every
flagged item: for example `UNEVIDENCED: #1234, #1240; UNATTRIBUTED: ad16c85b1, 56aafb02c;
DISPOSITIONED: 1`. That way R3's existing first-line excerpt carries the full enumeration, and
worker.md R3 does not need to change. The full per-item table follows on later lines.

Adding the row edits `.claude/agents/worker.md`, a protected surface. That edit goes through the
normal CODEOWNERS human gate. The coder does not author it (CLAUDE.md #1347).

**R12 — Do not touch the overseer section.** This work must not edit or remove
`overseer.md:170-220` (REQ-B8). REQ-B7's removal belongs to #1340, after #1622, #1623 and #1624 have
all landed.

**R13 — Reuse, do not re-implement.** Use `derive_range`, `_find_human_approval`, the
`require_overseer_approval` predicates, `list_pull_reviews` and `get_pull`. Any new GitHub read
(commit→PR) is added to `scripts/automation/lib/github.py`, paginated, with the same retry and
raise semantics. It must not be a hand-rolled `gh api` call in the suite (CLAUDE.md item 5).

## 4. Non-goals

- REQ-B2/B3/B4 (tier, findings and coverage at release) belong to #1622 and #1623. REQ-A13 belongs
  to #1625.
- Removing or editing `overseer.md`'s release-gate section (REQ-B7) is out of scope.
- Fixing the overseer's per-PR merged-by-bot heuristic (F4) is out of scope. Record it as a
  follow-up; do not fix it here.
- Making the audit trail durable is #1803. Activating `release_artifact_logic.py`'s stamp check is
  out of scope.
- Changing branch protection, required contexts or the overseer's review behaviour is out of scope.

## 5. Acceptance criteria (all unit-testable with fixtures; no live API in tests)

The tests inject GitHub responses at the `github.py` seam and git output at the `run_git` seam,
using the same monkeypatch idiom as `release_panel_logic`.

- **AC-1** Fixtures: a merge commit, a squash commit and two rebase-merged commits, each from
  distinct overseer-APPROVED PRs at head → exit 0. Each commit is attributed to the correct PR,
  with no reliance on commit-message parsing (R2, R3).
- **AC-2** A range commit with no associated merged PR → exit 1. The first line names its short
  SHA (R2).
- **AC-3** A commit whose only associated PR is closed-unmerged, or was merged into a non-default
  base → flagged as unattributed (R2).
- **AC-4** Overseer APPROVED, but `commit_id` ≠ the final `head.sha` → flagged (R4).
- **AC-5** Overseer APPROVED at head, but `submitted_at > merged_at` → flagged (R4).
- **AC-6** Overseer COMMENTED at head, `HUMAN_REVIEWER` APPROVED at head before merge, and the
  `require-overseer-approval` check-run fixture is `failure` → **EVIDENCED** (E-OVERSEER+HUMAN, the
  #1657 regression guard) (R4, R6).
- **AC-7** Overseer COMMENTED at head, and the APPROVED review is from `scottthurlow-claude[bot]` →
  flagged (R5).
- **AC-8** No overseer review at all, `require-overseer-approval` check run `success`, audit-trail
  fixture says reviewed → flagged. Neither informational source alone evidences a PR (R6).
- **AC-9** A PR comment from the overseer login reading "APPROVE" with no review object → flagged
  (R5).
- **AC-10** Overseer login and human login are read from a fixture `machine-accounts.env`. Changing
  the fixture value changes the outcome, which proves nothing is hard-coded (R4).
- **AC-11** Fail-closed (R9), each case producing exit 2, a distinct reason, and **no** flagged list
  presented as complete:
  - a `GitHubError` on the reviews read;
  - a `RateLimitError` on the commit→PR read;
  - a page-cap overflow;
  - a review missing `commit_id`;
  - an empty `BOT_OVERSEER_USERNAME`;
  - a range commit count ≠ classified count.
- **AC-12** A shallow clone, no tag, or an empty range → exit 2 with `derive_range`'s refusal text.
  There is never a `HEAD~1` or `origin/main` fallback (R1).
- **AC-13** A flagged PR plus a fixture disposition record that meets R8 → exit 0. The output lists
  it as DISPOSITIONED. The same record authored by a bot → still exit 1. A record naming a
  different PR → still exit 1 (R8).
- **AC-14** The first output line contains every flagged item's identifier when there are 30 or
  more flagged items. Line-length handling must not truncate the list (R11).
- **AC-15** A test asserts that the suite module never opens a path under `.claudetmp/` or
  `signoffs/`, and writes no files (R7).
- **AC-16** A grep-based test asserts that `overseer.md`'s "Release-gate deep validation (#695)"
  heading is still present (R12 / REQ-B8).
- **AC-17** `scripts/framework/run_tests_inner_loop.sh` passes.

## 6. Escalations — human decisions required (recommended default for each)

**ESC-1 — Do the original G-e roles survive? And the open window (F1).** #1340 defined G-e as
"code-review, security, privacy signed off APPROVED". REQ-B5's acceptance asks only for
overseer-gate evidence, and no durable per-role source exists, because the register is
gitignored and stamps are being retired.
(a) Is G-e's per-role element formally reduced to "the PR passed the overseer gate"?
**Recommended default: yes.** Record a DECISIONS.md entry, as a REQ-B0(ii) human-approved
reduction, naming what is no longer checked: the per-role APPROVED sign-off. The reasoning to
record: the overseer gate's own review is the durable per-PR evidence, and per-role register
entries were never verifiable from another clone.
(b) Acknowledge that G-e has been unchecked since `2abe9919b` (2026-09-14). **Recommended default:**
record the acknowledgement in the same DECISIONS entry. Do not reinstate any interim check, since
the removed one never fired.

**ESC-2 — Disposition mechanism (R8).** The options:
- **(A)** A comment by `HUMAN_REVIEWER` on the release-request issue, with a fixed parseable line
  (for example `Disposition: #1234, ad16c85b1 — <reason>`), read by author identity.
- **(B)** A post-merge `APPROVED` review by the human on the flagged PR itself, counted only as
  disposition, never as E-OVERSEER+HUMAN evidence.
- **(C)** A label applied by the human to each flagged PR, with the `labeled` event actor verified.

**Recommended default: (A).** It matches REQ-B3's existing "dispositioned on the release-request
issue" wording for the sibling #1622, so there is one disposition surface per release. It is
identity-bound, and it is a human decision record rather than a bot attestation. It also interacts
correctly with R1.9 check 3: "no human comment since" is false after a disposition, so the suite
re-runs instead of carrying forward the failure.

**ESC-3 — Human-merged PRs with no overseer review at all.** `overseer.md:152-158` says "human merge
authority supersedes the overseer review requirement". `require_overseer_approval.py` (#621) says a
human approval alone never satisfies the overseer gate. REQ-B5 asks whether the merge "passed the
overseer review gate", and an admin-override merge with no overseer review did not.
**Recommended default:** flag the PR, but label it with a distinct class `HUMAN_MERGE_NO_OVERSEER`,
so the human can recognise and disposition these in bulk by name under ESC-2. The alternative
would be to accept a human `APPROVED` review at head before the merge as a third evidence class.

**ESC-4 — Unattributed commits (direct pushes).** At least three exist in `v0.6.0..HEAD` (F5), all
bot audit-log commits. **Recommended default:** flag every one and give none a path-based
auto-exemption, because an exemption list is a new artifact that could be gamed. The human
dispositions them under ESC-2.

**ESC-5 — Should required check-run conclusions also be required per PR?** The issue lists
`oversight-gate-*`, `oversight-validator-*` and `tests` as candidate sources. **Recommended
default: no — informational only (R6).** Two reasons: those contexts serve G-a/G-c and belong to
the sibling issues, and a check-run is re-runnable after merge. If the human says yes, each run
must be GitHub-Actions-attributed and must have completed before `merged_at`.

**ESC-6 — The first run's backlog.** PRs merged before #1657 Part 2 (`f6a1aceb3`, 2026-09-24)
carry overseer verdicts as **comments**, not review objects, so R4/R5 flag them. That could be
dozens of PRs on the first v0.7.0 release. **Recommended default:** no grandfather cutoff and no
comment-based evidence. The human dispositions the pre-cutover PRs by name in one ESC-2 record.
The alternative is to accept an overseer-App-authored comment carrying the canonical
`**Decision: …**` header as a fourth class, `LEGACY_COMMENT_VERDICT`, for PRs merged before
`f6a1aceb3` only. That trades R5's strictness for less human effort.

## 7. Escalation flag (CORE self-flag)

RISK: HIGH. This builds a release gate, and a release gate that passes wrongly is worse than none.
It also touches a protected surface (the worker.md R2 row).
CONFIDENCE: 85%. I am confident in:
- F1 (`2abe9919b` verified on `origin/main`);
- F2, F3, F6, F7 and F8 (code read this session);
- the F5 shape counts.

I am not confident in two things:
- whether `ad16c85b1`, `56aafb02c` and `bbeef2617` truly have no PR association, which needs the
  commit→PR API;
- what review event the overseer posts today for at-or-below-ceiling protected-surface PRs after
  #1657. R4's E-OVERSEER+HUMAN handles either case.

Classification: **structural**. ESC-1(a) would formally reduce an approved guarantee. R11 adds a
required R2 suite at every tier, a new release-blocking condition. R8 introduces a new human
disposition step. Per CORE, none of these may be written into worker.md, overseer.md or the
contract without human sign-off. This document proposes them; it does not authorize them.

## Human Review Required

- **ESC-1..ESC-6** above. ESC-1 and ESC-2 must be answered before technical design. ESC-3..ESC-6
  have safe defaults that design can assume, but those defaults are not binding until the human
  confirms them.
- **`.claude/agents/worker.md` R2 table** (R11): this edits a protected surface and goes through the
  CODEOWNERS gate.
- **F1 contradicts the issue's premise**: REQ-B8's "no window" ordering has already been overtaken
  by `2abe9919b`. The human should know the window exists today, independently of this issue's
  delivery date.
