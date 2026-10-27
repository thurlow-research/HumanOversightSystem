# ADR-2047-2048: The declared-closes set is one script-written marker line in the PR body. One protected grammar module and one protected GitHub-reading module back three checks: the `edit_issue.sh` pre-write scan, a required `pull_request_target` check that re-runs on `edited`, and an overseer pre-merge call that pins `sha`. A post-merge workflow detects and notifies but never reopens

**Status:** ACCEPTED FOR DESIGN. AD-1 to AD-9 bind `technical-design`. Two items are **PROVISIONAL**:
- AD-1 (the record lives in the PR body, not in a comment) is provisional on ESC-1 as restated in §7. It is drafted on the architect's recommendation, and §7 names exactly what changes under the pm-agent default.
- AD-8 (post-merge: detect and notify, never reopen) is provisional on ESC-5.

AD-4's fail-closed rules, AD-3's "absent is not empty", AD-2's protected placement of the grammar, and AD-5's "read live, never from the event payload" are not open to any ESC answer or agent-side waiver.
**Date:** 2026-10-16
**Author:** architect (autonomous worker cycle; no human present, so open decisions are ESC/ARCH-ESC items with recommended defaults)
**Issues:** #2047, #2048 · **Parent:** #1856 · **Milestone:** v0.7.0 · **Risk tier: MEDIUM computed, human-gated by surface.** Every slice touches protected surface (`protected_surfaces.txt`): `bootstrap/**` (`:27`) and `scripts/framework/**` (`:28`) in S1; `scripts/framework/**`, `bootstrap/**` and `.github/workflows/**` (`:33`) in S2; `.claude/agents/**` (`:16`) and `CLAUDE.md` (`:19`) in S3; `scripts/framework/**` and `.github/workflows/**` in S4.
**Inputs:** `docs/v0.7.0/REQUIREMENTS-2047-2048-closing-keyword-post-open-guard.md` (committed `f29890f4d`: VF-1 to VF-9, REQ-1 to REQ-14, ESC-1 to ESC-7, TD-O1 to TD-O4). Files read for this ADR:
- `scripts/automation/closing_keywords.py` (whole file) and `bootstrap/submit_pr.sh` (whole file);
- `bootstrap/edit_issue.sh` (whole file) and `bootstrap/merge_authority.sh:1-60`;
- `.claude/agents/overseer.md:213,230-243,303,466-474,744,765,772` and `.claude/agents/worker.md:129,156`;
- `bootstrap/overseer-cron-prompt.md:16-62`;
- `.github/workflows/require-tier-ceiling.yml:1-80`, `require-human-approval.yml:25-45` and `rerun-gate-checks.yml` (whole file);
- `scripts/framework/rerun_gate_checks.py:1-80`, `scripts/framework/setup_branch_protection.sh:127,140-224` and `scripts/framework/hos_required_contexts.txt`;
- `scripts/framework/protected_surfaces.txt`, `scripts/framework/requester_trust.py:285-298` and `scripts/automation/lib/merge_authority.py:1020-1110`;
- `docs/v0.7.0/ADR-1357-merge-authority-execution.md` (AD-5 to AD-8, §4 build order), `docs/v0.7.0/TECHNICAL-DESIGN-1538-out-of-band-audit-logging.md` (§3, writer inventory `:94`, `:922`, `:976`, slice table `:1381`) and `docs/v0.7.0/TECHNICAL-DESIGN-1856-closing-keyword-guard.md` (§4, §8 D5, §11, §11a);
- `tests/framework/test_gate_checkout_pinned_base.py:33-76` and `.claude/settings.json`;
- `git log --first-parent origin/main` (merge-method evidence, AF-3).

**Consumers:** `technical-design` → `coder` → review chain.
- `security-reviewer` is mandatory on S1, S2 and S4. They read untrusted PR text in a privileged CI job, add a write-capable `pull_request_target` workflow, and move a security control's grammar.
- `reliability-reviewer` is mandatory on S2 and S4, which add a required check that can halt every merge and a GitHub-dependent post-merge job.
- S3 edits `.claude/agents/**`. Per CLAUDE.md (#1347), the top-level worker session authors those edits directly, never `coder`.

**Explicitly does NOT re-litigate:**
- TD-1856's grammar (§3, NG-1) and its no-exemption rule (D4);
- ADR-1357's decision matrix, AD-5 recompute, AD-6 staleness bar and AD-7 atomic approve+merge;
- TD-1538's audit envelope;
- the repo's allowed merge methods;
- `enforce_admins: false` (`setup_branch_protection.sh:127,168`).

---

## 0. Verification findings (working tree at `f29890f4d`)

### 0.1 Confirming pm-agent

- **VF-1 CONFIRMED.** `CLOSES_ARGS` (`submit_pr.sh:159,170`) reaches only the local check calls (`:268-325`). The audit helper (`:116-132`) records the *undeclared* keys, and only on refusal. Nothing persists the declared set.
- **VF-2 CONFIRMED.** `edit_issue.sh` PATCHes `repos/<slug>/issues/<N>` (`:195`), with `title` (`:176`) and `body` (`:186`) unscanned. Label-only edits never GET the item first (`:201-213`).
- **VF-3 CONFIRMED, and wider than stated.** The overseer PUTs `{"merge_method":"squash"}` with no `sha` and no message. It does so at **four** sites, not two:
  - `overseer.md:466` (AUTO_MERGE);
  - `:467` step (3) (the HUMAN_REQUIRED/CRITICAL "merge immediately — unconditional" path);
  - `:474` (batch merge step 4);
  - `:772` (the tool table).
  See AF-6.
- **VF-4 CONFIRMED.** `bootstrap/` has no `overseer_merge.sh` and `scripts/automation/` has no `overseer_decide*`. ADR-1357 §4 slices 2 to 6 are unbuilt, and slice 4 is blocked on its ESC-1.
- **VF-5 CONFIRMED.** The gate workflows trigger on bare `pull_request_target` (`require-tier-ceiling.yml:46-48`), which means the default activity types and no `edited`. The #972/#1299 lessons live in the workflow headers (`require-tier-ceiling.yml:30-44`, `rerun-gate-checks.yml:1-31`) and in `tests/framework/test_gate_checkout_pinned_base.py`, not in `DECISIONS.md`. A grep of `DECISIONS.md` for `972|1299` finds nothing.
- **VF-7 CONFIRMED.** `closing_keywords.py:133` hard-codes `✘ submit_pr.sh:` and `:139` hard-codes "pass --closes <n>".
- **VF-8 / TD-O3 ANSWERED.** `edit_issue.sh` is **not** shipped either. It is absent from `framework_consumer_files.txt` and from `hos_install.sh`'s explicit `bootstrap/` copy list, the same evidence TD-1856 §11a recorded for `submit_pr.sh`. NG-4 holds without a consumer-safe path.

### 0.2 Architect findings (these change the design)

**AF-1 (HIGH): the grammar every check will trust is on unprotected surface.**
- `scripts/automation/**` is not in `protected_surfaces.txt`.
- An overseer-auto-mergeable PR (LOW to HIGH tier, no protected path) can therefore weaken `closing_keywords.py`'s regex. Every guard then inherits the weakened regex: today's `submit_pr.sh` guard, the proposed CI check and the merge check.
- The `pull_request_target` "trusted base copy" defence does not help, because once such a PR merges, the weakened copy *is* the base copy.
- TD-1856 §4 placed the module by the thin-wrapper precedent and never considered protection. My own §11a review approved that path ("the path is sound") and missed this. AD-2 moves the module, and §6 records it as a startup gap.

**AF-2 (HIGH): a comment-based record races the `opened` check run on every declared PR.**
- `submit_pr.sh` can post a comment only *after* `gh pr create` (`:399`). The `pull_request_target: opened` run starts independently and may read the comments before the record exists.
- A PR with a legitimately declared `closes #12` would then fail its first check run, nondeterministically. Recovering needs a second trigger (`issue_comment`), which is exactly TD-O4's #972/#1299 hazard. Under #1299, an extra trigger produced a duplicate check run whose stale FAILURE kept blocking (`require-tier-ceiling.yml:36-44`).
- A record in the PR body is created **atomically with the PR**, and every later change to it fires `pull_request_target: edited` on the same workflow. That removes the race, the comment trigger and the `post_comment.sh`/`escalate_to_human.sh` refusals (AD-1, AM-1).

**AF-3 (HIGH): the human merges with all three methods, not only squash.** `git log --first-parent origin/main` shows three kinds of commit:
- squash merges with an empty body (`ff26c5527 … (#2106)`, `6c60f5a73 … (#2098)`, committer `GitHub`);
- a true merge commit (`c785a534e Merge pull request #2103 …`, two parents);
- single-parent branch commits committed by `Scott Thurlow` that carry their own bodies (`ca593f0a2`, `95c5704fa`, …). These come from a rebase merge or a direct push.

Two consequences follow:
- VF-6(c) ("the branch's own commits never reach `main` under squash") is not the operative case for human merges. Every branch commit message can land on `main` and close issues. REQ-7's commit scan is therefore load-bearing, not belt-and-braces.
- The squash default in effect today is evidently **PR title + blank body**. That is strong evidence for TD-O1, and S2 confirms it from the repo settings.

**AF-4 (HIGH): the required check bounds the overseer, but not the human.** `enforce_admins: false` (`setup_branch_protection.sh:127,168`) leaves the admin (the CODEOWNER) a bypass of every required check in the merge UI.
- REQ-7 therefore *prevents* only for non-admin merges, which in this repo means the overseer.
- For the human, it is a red check they can click past.
- The requirements' coverage matrix (§3) overstates REQ-7 for P2 and P5 when a human does the merging. AD-8's post-merge detection is the only control after a bypass, and the threat model in §3 below says so.

**AF-5 (HIGH): untrusted PR text printed in a CI job can drive the Actions runner.** GitHub Actions interprets workflow commands (`::error::`, `::add-mask::`, `::stop-commands::`, `::group::`, …) on job stdout and stderr. The refusal report quotes body lines (`closing_keywords.py:135`). A body line such as `::add-mask::…` or `::error file=…::` would be executed by the runner as a command, not printed as data. This is a new attack surface that the local-only #1856 guard never had. AD-5 binds the mitigation.

**AF-6 (MEDIUM): the merge sites outnumber what REQ-8/REQ-13 name.** `overseer.md:467` step (3) and `:474` step 4 also merge. If REQ-8 wires only `:466` and `:772`, the CRITICAL path, which is the path the human just approved and the one most like #1725, merges unguarded. AD-6 binds all four sites, and a test enumerates them.

**AF-7 (MEDIUM): the CI and post-merge phases cannot write REQ-12's audit event.**
- `closing-keyword-refused` is written to the clone-local `audit/log/**` through `scripts/oversight/lib/audit_log.sh` (`submit_pr.sh:116-132`).
- A GitHub-hosted runner has no persistent clone and cannot commit.
- For `phase: ci` the durable record is the check run itself plus its job summary. For `phase: post-merge` it is the issue comment and label (AM-9).

**AF-8 (MEDIUM): TD-1538's writer inventory predates #1856.** TD-1538 lists `submit_pr.sh`'s `_hos_audit_stale_base_merge` (`:94`, `:976`) but not `_hos_audit_closing_keyword_refusal`. It would migrate one helper and leave its sibling on the hand-built `printf` JSON path. FU-2 names this, and AD-9 adds no third hand-built writer.

**AF-9 (MEDIUM): where required checks are enforced is itself uncertain.** `merge_authority.py:1066-1070` says "this repo's required checks live [in rulesets], and the overseer App gets 403 on the classic endpoint (#1731, #1588)". `setup_branch_protection.sh` writes the *classic* `required_status_checks`. Adding a line to `hos_required_contexts.txt` activates nothing by itself. Activation is an operator act against whichever mechanism the live repo enforces (§6, ARCH-ESC-1). Because the overseer's pre-merge call (AD-6) does not depend on that configuration, a misconfigured activation leaves the overseer path guarded regardless.

**AF-10 (LOW): `--update-pr` never touches the body.** `submit_pr.sh:186-187` rejects `--title`/`--body-file` in update mode, and its scan covers commits only (`:321-324`). REQ-1's "update mode writes a new record when `--closes` is passed" would add a body PATCH to a mode designed never to edit PR metadata. AM-3 routes declaration amendments through `edit_issue.sh` alone.

**Reuse search (CLAUDE.md item 1).** I searched `scripts/`, `bootstrap/`, `bin/` and `scripts/automation/lib/` for:
- a PR-body or closing-reference reader;
- a `closingIssuesReferences` query;
- a trusted-login loader;
- a `pull_request_target` gate pattern;
- an in-place rerun dispatcher.

Results:
- Found: `closing_keywords.py`, the grammar. It is reused unchanged in logic and moved (AD-2).
- Found: `requester_trust.load_trusted_apps` (`:285-298`), the three HOS App logins and never Copilot. It is reused for AD-4.
- Found: the `require-*` workflow pattern (base-SHA checkout, `persist-credentials: false`, PR read as data). It is reused (AD-5).
- Found: `rerun_gate_checks.py`. It is **not** extended by default, because AD-5 uses the native `edited` type. It is the named fallback if S2's supersession probe fails.
- Found: `merge_authority.check_required_content_checks` (`:1045`). It already bounces any failing non-meta required check to the worker. A failing `closing-keyword-guard` is worker-fixable (`edit_issue.sh`), so it must **not** be added to `_META_GATE_CHECKS` (`:1026`). This gives the remedy loop for free.
- Found nothing that queries `closingIssuesReferences`. `scripts/automation/lib/github.py` was rejected as the read path for ADR-2102 AF-2's reasons: it is unprotected, and it treats a 404 as "empty".

---

## 1. Organizing principle

**What closes an issue is GitHub's to decide, and we cannot intercept it. What the author *meant* to close is one line that only HOS scripts write. Every check computes the same two things, the actual closing set and the declared set, with the same protected code, and fails closed when they differ or when either cannot be read.** Local checks give agents early feedback. The required server-side check is the only preventive control on paths HOS code does not run. The overseer re-runs that check immediately before it merges. Once a human has merged, nothing can prevent the closure, so the design detects it and tells the human. It does not overrule them.

---

## 2. Decisions

### AD-1: The declared-closes record is exactly one marker line in the PR body, written only by HOS scripts. It is honoured only when the PR's author is trusted. (BINDING on the trust and format rules; PROVISIONAL on location, ESC-1. REQ-1, REQ-2, REQ-4, AF-2.)

- **Format.** One whole line, `<!-- hos-closes v=1 refs=<k1>,<k2>,… -->`. `refs=` may be empty, which declares the empty set.
  - The keys are TD-1856 §3 normalized keys: a bare number for this repo, or `owner/repo#n` lowercased.
  - They are sorted and de-duplicated.
  - The `v=1` token sits between `hos-closes` and `refs`, so the grammar's KEYWORD (`closes`) is never followed by a REF. A test asserts that `find_closing_refs` returns nothing for every rendered marker, including cross-repo keys.
- **Parse (one function, `closing_keywords.parse_marker(body)`):**
  - count body lines that match `^<!-- hos-closes v=1 refs=(<key>(,<key>)*)? -->$` exactly;
  - **exactly one** → declared set;
  - **zero** lines that start with `<!-- hos-closes` → **absent**;
  - **more than one**, or any line that starts with `<!-- hos-closes` and does not parse → **invalid**, which is treated as absent and reported as `marker invalid: <why>`;
  - unknown `v=` → invalid.
- **Writers (only these):**
  - `submit_pr.sh` open mode appends the marker to its private body snapshot. This happens always, including `refs=` when no `--closes` was passed (REQ-1's "explicitly empty").
  - `edit_issue.sh` on a PR carries the current marker forward, or rewrites it with `--closes` (AD-4).
  - The human, by hand, on PRs they author (AD-3).
- **Anti-quotation rule.** `submit_pr.sh` and `edit_issue.sh` **refuse** a caller-supplied body that already contains any line starting with `<!-- hos-closes`. A copied body can therefore never smuggle in another PR's declaration through the sanctioned paths. This replaces REQ-2's `post_comment.sh`/`escalate_to_human.sh` refusals (AM-1): comments are no longer a declaration channel, so nothing in a comment can declare.
- **Trust rule (AD-3 applies it):** the marker counts only if the PR author's login (case-insensitive) is in `load_trusted_apps(repo_root)` (worker, overseer, human Apps) or equals `HUMAN_REVIEWER` from `machine-accounts.env`.
  - **Why author rather than editor.** Editing another user's PR body requires write access to the repository. On a trusted author's PR, every possible editor is therefore a write collaborator: the HOS Apps or the CODEOWNER.
  - **On any other author's PR, including forks, the marker is ignored.** Every closing reference is then undeclared. The CODEOWNER's remedy is to edit the closing text out and close the issue by hand.
  - Single-CODEOWNER scope holds until #1936 (pm ESC-2).
- **Why not the pm default (a trusted PR comment).**
  - It races `opened` (AF-2).
  - It needs a second trigger with a #1299 duplicate-check-run history.
  - It needs edits to two more protected scripts.
  - Its forge resistance against an agent that bypasses the wrappers is the same as the body's: a raw `gh api` POST forges a bot-authored comment as easily as a raw PATCH forges a body line.
- **The pm-agent's two objections to the body, answered.**
  - "Any body edit can drop it." The sanctioned edit path carries the marker forward (AD-4). A dropped marker reads as **absent**, which fails closed (AD-3). That is the safe direction, and the failure is visible.
  - "It would land in the squash message." Today's default body is blank (AF-3). Under a body-including default, the marker is an inert HTML comment with no closing keyword. AD-6 does not put the body in the merge request either way.
- **Residual R-1.** A write collaborator can deliberately forge or edit the line, through the UI or a raw API call. Deliberate circumvention by a write-access agent is out of reach of any text record. AD-8 detects the closure after the fact, and the line is visible in the PR body for review.

### AD-2: One grammar, on protected surface. `git mv scripts/automation/closing_keywords.py scripts/framework/closing_keywords.py`, unchanged in logic, plus the marker and report helpers. (BINDING; REQ-11, AF-1.)

- **The move.**
  - `submit_pr.sh:199` `CK_PY` is updated.
  - The existing tests keep their assertions. Only their module path changes.
  - No shim is left at the old path, because a shim in unprotected space would re-open AF-1.
- **Additions, all stdlib and network-free:**
  - `parse_marker(body) -> Declared | Absent | Invalid(reason)`.
  - `render_marker(keys) -> str`.
  - `format_report(undeclared, *, caller, remedy) -> str`, with `caller` from a closed enum {`submit_pr.sh`, `edit_issue.sh`, `closing-keyword-guard`, `overseer pre-merge`, `post-merge`} and `remedy` from a closed enum {`rephrase-or-closes`, `rephrase-or-human-marker`, `pushed-escalate`}.
  - The CLI's `check` gains `--caller`, default `submit_pr.sh`, so `submit_pr.sh`'s output is byte-identical (REQ-11's "stays as it is now"; the TD-1856 §10 tests must pass unmodified).
  - A `compose-pr-body` subcommand serves `edit_issue.sh` (AD-4). All marker parsing and rendering stays in Python, and bash only moves files.
- **Import rule.** `closing_keywords.py` imports nothing outside the standard library. `closing_guard.py` (AD-5) imports `closing_keywords` and `requester_trust` by file path from `scripts/framework/`, and **nothing** from `scripts/automation/**` or `scripts/oversight/**`. An AST test pins this, as ADR-2102 AD-1 did.

### AD-3: Absent is not empty, and every check computes the same two sets. (BINDING, not waivable; REQ-3.)

- **Declared set.**
  - Trusted author + valid marker → that set.
  - Trusted author + absent or invalid marker → **undeclared** (the empty set, with the report saying `no declaration record` or `marker invalid: …`).
  - Untrusted author → **undeclared**, whatever the body says, with the report saying `author <login> cannot declare`.
- **Actual closing set.** The union of:
  - (a) `find_closing_refs` over the **current title, current body and every PR commit message**;
  - (b) GraphQL `closingIssuesReferences` (manual Development links included), normalized to the same keys.
- **Verdict.** It passes iff actual ⊆ declared. A PR with an empty actual set passes regardless of the record (REQ-3's second AC). Any read, parse or pagination-bound failure is a failure, never a pass:
  - commits are capped at GitHub's 250 per PR, and 250 returned commits counts as a failure;
  - `closingIssuesReferences` is read with `first:100`, and `hasNextPage` counts as a failure.
- **Why scan commits in every check.** AF-3: human merges bring branch commits to `main`. The scanned set (title ∪ body ∪ commits) is a superset of every message GitHub can compose by default: title-only, title+body, or title+commit list. This is what makes AD-6's "do not compose a message" safe.
- **One function.** `closing_guard.evaluate(repo, pr) -> Verdict{result, head_sha, actual, declared, declared_state, undeclared[], errors[]}`. The CI job, the overseer pre-merge call and the post-merge job all call it. `edit_issue.sh` uses `closing_keywords` directly on the bytes it is about to write (AD-4). No second regex, and no second set computation.

### AD-4: `edit_issue.sh` checks a PR's title or body *before* writing, carries the marker forward, and is the only path that amends a declaration. (BINDING; REQ-5, REQ-6, AM-2, AM-3.)

- **Scope.** The new path runs only when `--title`, `--body-file` or `--closes` is given. Label, milestone, assignee and state-only invocations make no new GET and call no Python. They are byte-identical to today, so `needs-human`/`needs-ai` labelling never depends on `python3`.
- **Steps (new path):**
  1. GET `issues/<N>` once and read `pull_request`, `title`, `body` and `user.login`. A read failure refuses. It never falls back to "it's an issue".
  2. **Issue (no `pull_request`):** today's behaviour, unchanged. `--closes` on an issue is a usage error before any write.
  3. **PR:** run `python3 -I scripts/framework/closing_keywords.py compose-pr-body --current-body-file <snap> [--new-body-file <caller>] [--closes …] --title <resulting title> --repo-slug … --caller edit_issue.sh --out <private copy>`. That command:
     - refuses a caller body that contains a marker line (AD-1);
     - takes the resulting body, which is the caller's body if one was given and otherwise the current body with its marker removed;
     - takes the resulting set, which is the current valid marker's set ∪ `--closes`. If the current marker is absent or invalid, it is `--closes` alone, and with no `--closes` it stays **absent**, with no marker appended;
     - appends `render_marker(set)` when the set is present;
     - scans the resulting title and body against the set. Undeclared → exit 1, with the refusal (remedy `rephrase-or-closes`) and nothing written.
  4. PATCH exactly the bytes of `<private copy>` (the TOCTOU rule of `submit_pr.sh:203-213`), plus the title if given, in the **same single PATCH** as today (`:194-196`).
- **The declaration rides inside the body PATCH, so declaring and editing are one atomic write.** REQ-6's "write the record after the PATCH" ordering disappears.
- **`--closes` alone on a PR is allowed (AM-2).** It re-renders the marker on the current body and re-scans. This is how a worker answers a failing `closing-keyword-guard` for an intended closure, and how `--update-pr` commits get declared (AM-3).
- **Missing `python3` or module on the new path** → refuse (REQ-12).
- **Audit.** A refusal writes `closing-keyword-refused` with `phase: edit`, the PR number, the undeclared keys and the declared set, through the best-effort helper pattern of `submit_pr.sh:116-132`. An audit failure never masks the refusal.

### AD-5: Required check `closing-keyword-guard`: a new `pull_request_target` workflow with native `edited`, base-SHA checkout, and live reads only. (BINDING; REQ-7, AF-2, AF-4, AF-5, TD-O4.)

- **Workflow** `.github/workflows/closing-keyword-guard.yml`. Job `name: closing-keyword-guard` must equal the required context (#737).
  - `on: pull_request_target: {types: [opened, edited, synchronize, reopened], branches: [main]}`. Only the default branch, because closing keywords close nothing on `release/v*` merges.
  - `concurrency: {group: closing-keyword-guard-<pr>, cancel-in-progress: true}`.
  - `permissions: {contents: read, pull-requests: read, issues: read}`.
  - `actions/checkout` with `ref: ${{ github.event.pull_request.base.sha }}` and `persist-credentials: false`, the #972 pin, even though `pull_request_target` already defaults to base. `test_gate_checkout_pinned_base.py` gains this workflow.
  - No PR content is checked out or executed.
  - No `${{ github.event.pull_request.title/body/head.ref }}` interpolation into `run:` (classic script injection). Only the PR **number** and repository go through `env:`.
- **Live reads, never the event payload.** `closing_guard.py ci --pr <N>` reads title, body, author, head SHA, commits and `closingIssuesReferences` from the API at run time. A rerun (any mechanism) therefore re-evaluates current state, the same idempotence `rerun_gate_checks.py` relies on (`:14-17`).
- **Why native `edited` and not an `issue_comment` or rerun dispatcher.** Under AD-1, every declaration change *is* a body edit, so `edited` covers declarations, UI edits (P2) and human PRs (P5) with one trigger on one workflow. No new `actions: write` job is created.
- **Supersession probe (S2 obligation, decides the fallback).** On a scratch PR, S2 records three cases in `research/findings/api-field-shape-verification.md`:
  - (i) `opened` fails, then `edited` passes;
  - (ii) `opened` passes, then `edited` fails;
  - (iii) a cancelled in-progress run followed by a completed one.

  For each case it records whether branch protection's merge-ability follows the **newest** run of `closing-keyword-guard` on the head SHA.
  - (ii) must block. If it does not, S2 does not merge, and the design returns to me, because that would be a fail-open.
  - If (i) leaves a stale FAILURE blocking (a liveness defect, the #1299 symptom), S2 adds `closing-keyword-guard` to `rerun_gate_checks.py`'s `GATE_WORKFLOWS` with a `pull_request_target: edited` dispatcher entry instead. That is a protected-surface change already inside S2's file budget.
- **Untrusted text in CI (AF-5), mandatory:**
  - Every string from GitHub is passed through ADR-2102 AD-5's sanitizer before printing: C0/C1, DEL, bidi and zero-width removed, truncated with `…[+N chars]`. A copy is acceptable until ADR-2102 FU-1's shared lib exists.
  - In `ci` mode the script first emits `::stop-commands::<random 32-hex token>` and ends with `::<token>::`, so no line of PR text is interpreted as a workflow command.
  - The job summary (`$GITHUB_STEP_SUMMARY`) renders snippets inside fenced code with backticks neutralized.
  - A test feeds `::add-mask::x`, `::error::x`, `::stop-commands::x` and ANSI/OSC in a body line, and asserts that the emitted stream contains the stop-commands envelope before the first untrusted byte.
- **Exit and report.** Exit 0 means pass. Exit 1 means undeclared refs, listed per key with source and line. Exit 2 means a read, parse or bound failure, and the job fails. The report uses `format_report(caller="closing-keyword-guard", remedy=…)`:
  - `rephrase-or-closes` for bot-authored PRs: "edit with `edit_issue.sh --closes <n>` if intended";
  - `rephrase-or-human-marker` for the CODEOWNER's PRs: the one-line marker recipe;
  - for untrusted authors: remove the closing text.
- **Not a meta gate.** `closing-keyword-guard` must not be added to `merge_authority._META_GATE_CHECKS`. A failure is worker-fixable, so `check_required_content_checks` bounces the PR to the worker (`overseer.md:303`). A test pins the absence.
- **Registration.** `scripts/framework/hos_required_contexts.txt` gains `closing-keyword-guard` (HOS-only, so not shipped), with its producer and rationale comment. **Activation is an operator act** (AF-9, ARCH-ESC-1). The line merging activates nothing.

### AD-6: Merge time. The overseer runs the same check immediately before **every** merge PUT and pins the PUT to the evaluated `sha`. It does not compose a commit message. (BINDING; REQ-8 as amended by AM-5, REQ-9, AF-3, AF-6.)

- **Primitive.** `bootstrap/closing_guard.sh check --pr <N> --app <role>` is a thin wrapper in the `bootstrap/merge_authority.sh` style:
  - it mints with `get_app_token.sh`, so there is no ambient-token expiry, `exec`s `python3 -I scripts/framework/closing_guard.py check --pr <N>`, and revokes the token;
  - no logic and no JSON of its own;
  - its stdout is one JSON object: `{result: clean|undeclared|error, head_sha, actual[], declared[], declared_state, undeclared[{key, source, line}], errors[]}`;
  - exit 0 clean, 1 undeclared, 2 error;
  - read-only, and it can merge nothing.
- **Overseer wiring (all four sites: `overseer.md:466`, `:467` step 3, `:474` step 4, `:772`).** Immediately before the merge, run the wrapper.
  - **Only on `result: clean`:** `gh api --method PUT repos/{o}/{r}/pulls/<n>/merge -f merge_method=squash -f sha=<head_sha from that output>`. Literal values, with no PR text in argv.
  - On exit 1 or 2, or on absent or unparseable output: do not merge. Use the existing merge-failure handling (`:466`: `post_comment.sh` naming the keys, then the `needs-human` label), plus the `phase: merge` audit event.
  - **A silently skipped call (the #1146 denial mode) produces no JSON and therefore no merge.** The prose says "no clean JSON, no PUT" in those words.
- **Why no composed message (ESC-3 withdrawn, AM-5).**
  - AD-3 scans title ∪ body ∪ commits, a superset of every default composition. The default in force is title + blank body (AF-3).
  - The PR body closes issues through `closingIssuesReferences` whatever the commit message says, so composing a message cannot remove that closing source. Only the check can.
  - A model-composed `commit_title`/`commit_message` would put untrusted PR text into the overseer's argv or JSON, which is an injection and allowlisting hazard, for no closing-surface reduction.
  - The `sha` pin is the part of REQ-8(d) that carries weight: a push after the check makes the merge fail with 409 rather than merge unevaluated commits.
- **Why keep a merge-time call at all, when the required check gates the overseer (it is not an admin)?**
  - It does not depend on how required checks are configured (AF-9).
  - It covers the window before activation.
  - It covers a Development link added after the last check run. No PR event fires for that, so this is the only pre-merge read that sees it.
  - It costs one read-only call.
- **#1357 slice 4 (REQ-9).** When `overseer_merge.sh` lands, it calls `closing_guard.evaluate()` **in-process** as part of its AD-5 recompute. It refuses (exit 3) on a non-clean result, sends `sha` in its PUT, and the overseer prose then drops the separate wrapper call. FU-1 asks #1357's TD to record this. Nothing here pre-empts ADR-1357. There is no second mutation wrapper, because the PUT stays the overseer's existing call until slice 4 replaces it.

### AD-7: `submit_pr.sh` writes the marker in open mode. Update mode is unchanged. (BINDING; REQ-1 as amended by AM-3, AF-10.)

- **Open mode.**
  - Refuse a body that contains a `<!-- hos-closes` line.
  - Append `render_marker(declared)` to `BODY_COPY` **before** phase 1, so both phases scan the exact bytes that `gh pr create --body-file "$BODY_FILE"` (`:399`) sends.
  - The marker is written even when `--closes` is absent (`refs=`).
- **Update mode** (`--update-pr`): no body read and no body write. `--closes` keeps its current local meaning, declaring for the commit scan. The refusal remedy gains one line: "the PR's declaration is amended with `edit_issue.sh --number <N> --closes <n> --app worker`; `closing-keyword-guard` checks the PR's commits against it". The local check may pass while the server check fails on a commit key not yet in the marker. That is the intended split: the marker is the PR's single declaration, and one script amends it.

### AD-8: Post-merge detection. Notify the human on the closed issue and never reopen. (PROVISIONAL on ESC-5; BINDING on "never reopen" unless the human selects ESC-5 (a). REQ-10 as amended by AM-6, AF-4.)

- **Workflow** `.github/workflows/closing-keyword-postmerge.yml`.
  - `on: pull_request_target: {types: [closed], branches: [main]}`, with `if: github.event.pull_request.merged == true`.
  - Base-SHA checkout with `persist-credentials: false`, and `permissions: {contents: read, pull-requests: read, issues: write}`. This is the first `issues: write` job driven by a PR event, which is why `security-reviewer` is mandatory on S4.
- **Logic** (`closing_guard.py post-merge --pr <N>`). It uses `evaluate()`'s sets, read live after merge, plus a scan of the merge commit's own message (`GET /commits/{merge_commit_sha}`). That last source is the only text a human can type in the merge dialog (P4).
  - For each undeclared candidate, read the issue. It is a closure *by this merge* when the issue is closed and its latest `closed` event's `commit_id == merge_commit_sha`, or the event is otherwise attributable to this PR.
  - Ambiguous evidence counts as a closure, which errs toward telling the human.
  - For each such issue it posts one comment and adds `needs-human`. The comment:
    - names the PR, the merge commit and the matching text, sanitized per AD-5;
    - neutralizes `@` mentions;
    - is idempotent through a `<!-- hos-closing-guard post-merge pr=<N> -->` marker it checks for first.
  - The label puts the closure into the human's `needs-human` digest (ADR-2102).
- **Never reopen (architect recommendation, ESC-5 (b)).**
  - The only paths that reach this job are a human's own acts: an admin bypass of a red check (AF-4), text typed in the merge dialog, or a manual link added after the last check. Plus defects in this guard. A bot reopening what the trust root just closed overrules the human with less information than they had.
  - Reopening also re-exposes the issue to worker selection, which risks duplicate work.
  - The human re-opens with one click from the digest.
- **Failure.** Any read failure fails the run visibly (red X on the merge commit's workflow list). That record is weak, and it is stated as residual R-3.

### AD-9: Audit, failure direction, docs. (BINDING; REQ-12, REQ-13, AM-9.)

- **Audit.** Local phases only: `edit` (AD-4), `merge` (AD-6, written by the overseer via its existing ledger and audit path) and today's `text`/`full` (`submit_pr.sh`). The CI and post-merge records are the check run, its job summary, and the issue comment and label (AF-7).
  - No new hand-built JSON writer is added. `edit_issue.sh` reuses the same best-effort helper shape as `submit_pr.sh:116-132`.
  - When TD-1538 S1 lands, both migrate to `audit_append` together (FU-2).
- **Fail-closed table.** See §3.
- **Docs, in one human-reviewed slice (S3):**
  - `overseer.md`: all four merge sites, plus the `:744` `edit_issue.sh` row ("on a PR, title/body/`--closes` edits are scanned; the marker is carried forward");
  - `worker.md:129` (the same row note), plus `:156`'s mention that `edit_issue.sh` works on PRs;
  - `CLAUDE.md` "What to do instead" item 5: `edit_issue.sh` on a PR is now scanned, `--closes` amends the declaration, and agents never hand-write or copy a `<!-- hos-closes` line.
- **Docs elsewhere.**
  - The `submit_pr.sh` and `edit_issue.sh` headers are in S1.
  - The `TECHNICAL-DESIGN-1856` §8 D5 and §11 dated note is in S1.
  - `docs/LABELS.md` gets the post-merge `needs-human` use in S4.

---

## 3. Threat model and failure modes

**Trust boundaries.**
- Issue and PR text (titles, bodies, commit messages, branch names) is untrusted data in every check. It is never interpolated into `run:`, argv or JSON composed by a model.
- The trusted inputs are the base-branch code, `machine-accounts.env` and GitHub-computed fields (author login, head SHA, merge SHA, event commit ids).
- The CODEOWNER human is the trust root. Their merge can be **detected, never prevented** (AF-4).

**Coverage (replaces requirements §3):**

| Path | Prevent | Backstop |
|---|---|---|
| P0 open via `submit_pr.sh` | #1856 local scan + marker (AD-7) | CI (AD-5), pre-merge (AD-6), post-merge (AD-8) |
| P1 `edit_issue.sh` title/body on a PR | Local pre-write scan (AD-4) | CI, pre-merge, post-merge |
| P1' raw `gh api` PATCH by an agent | CI (non-admin merges); pre-merge | Post-merge |
| P2 UI edit (title/body) | CI for non-admin merges; **advisory only for an admin** | Pre-merge (overseer), post-merge |
| P2' manual Development link | Pre-merge (overseer) only: no event re-runs CI | Post-merge |
| P3 overseer squash merge | CI via branch protection + pre-merge + `sha` pin | Post-merge |
| P4 human merge: typed message, admin bypass, merge commit, rebase | **None possible** (CI is advisory for an admin) | Post-merge only |
| P5 PR opened outside `submit_pr.sh` | CI (marker honoured only for the CODEOWNER's own PRs) | Pre-merge, post-merge |

| Failure | Behaviour | Direction |
|---|---|---|
| API, GraphQL or auth failure in any check | Exit 2 / `error`; CI red, no merge, `edit_issue.sh` refuses | Closed |
| ≥250 commits or `closingIssuesReferences.hasNextPage` | Treated as failure | Closed |
| Marker absent, invalid or duplicated | Undeclared; every closing ref fails | Closed |
| Marker on an untrusted author's PR | Ignored | Closed |
| Caller body contains a marker line | `submit_pr.sh`/`edit_issue.sh` refuse | Closed |
| Body line carrying `::workflow-command::` or ANSI/OSC | Inside the stop-commands envelope; sanitized | Closed (AF-5) |
| `python3` or module missing | Refuse (PR title/body path only; label edits unaffected) | Closed |
| Overseer wrapper call denied or skipped (#1146) | No clean JSON, so no PUT | Closed |
| Head moved after the pre-merge check | PUT 409 on `sha` mismatch, then existing failure handling | Closed |
| Newest-run supersession does not hold | S2 does not merge as designed; rerun-dispatcher fallback (AD-5) | Liveness fix, decided by probe |
| Post-merge job read failure | Red workflow run; no notification | **Open (R-3)** |

**Residuals (stated, not hidden).**
- **R-1.** A write collaborator can deliberately forge the marker (AD-1). Detection is AD-8.
- **R-2.** A manual Development link added after the last CI run and merged by an admin is caught only post-merge.
- **R-3.** If the post-merge job itself fails, the only signal is a red workflow run that nobody is summoned to. FU-4 suggests the overseer's existing between-cycle merge audit (`overseer-cron-prompt.md:28-36`) check for a failed `closing-keyword-postmerge` run.
- **R-4.** A direct push to `main` (no PR) is outside every check here. It belongs to branch protection, not this guard.
- **R-5.** Before activation (ARCH-ESC-1), CI is advisory for everyone, and only AD-6 guards the overseer path.

---

## 4. Slices (each ≤15 files including tests, ≤10 commits, independently mergeable)

| # | Slice | Files (indicative) | Protected? | Depends on | Merge hangs on |
|---|---|---|---|---|---|
| **S1** | Grammar move and marker; both local write paths. AD-1, AD-2, AD-4, AD-7, REQ-11. One human review covers every `bootstrap/` behaviour change. | `scripts/framework/closing_keywords.py` (moved + `parse_marker`/`render_marker`/`format_report`/`compose-pr-body`/`--caller`), `scripts/automation/closing_keywords.py` (deleted), `bootstrap/submit_pr.sh` (path, marker append, marker refusal, update-mode remedy line, header), `bootstrap/edit_issue.sh` (AD-4, header), `tests/automation/test_closing_keywords.py` (path + marker/report/compose cases), `tests/automation/test_submit_pr.py` (harness path + marker cases), `tests/automation/test_edit_issue.py` (AD-4 cases), `SCRIPTS-INDEX.md`, `docs/v0.7.0/TECHNICAL-DESIGN-1856-closing-keyword-guard.md` (dated note §8 D5/§11): **9** | **Yes**: `bootstrap/**`, `scripts/framework/**` | — | ESC-1 (restated), ESC-2. `security-reviewer` |
| **S2** | Evaluator, required check and pre-merge primitive. AD-3, AD-5, AD-6 primitive (no caller yet). | `scripts/framework/closing_guard.py` (new: `evaluate`, `ci`, `check`), `bootstrap/closing_guard.sh` (new thin wrapper), `.github/workflows/closing-keyword-guard.yml` (new), `scripts/framework/hos_required_contexts.txt`, `tests/framework/test_closing_guard.py` (new: sets, trust, bounds, failures, AF-5 envelope, AST import rule, not-a-meta-gate), `tests/framework/test_closing_guard_wrapper.py` (new: argv, mint/revoke, passthrough), `tests/framework/fixtures/closing_guard/` (1-2 JSON), `tests/framework/test_gate_checkout_pinned_base.py` (add workflow), `research/findings/api-field-shape-verification.md` (TD-O1 setting, TD-O2, supersession probe), `SCRIPTS-INDEX.md`; **+2 only on the probe fallback**: `scripts/framework/rerun_gate_checks.py`, `.github/workflows/rerun-gate-checks.yml`: **10 (12)** | **Yes**: `scripts/framework/**`, `bootstrap/**`, `.github/workflows/**` | S1 | ESC-6, the supersession probe (ii) result. `security-reviewer`, `reliability-reviewer` |
| **S3** | Overseer wiring and all agent/CLAUDE.md prose. AD-6 wiring, AD-9 docs. Authored by the top-level session (#1347). | `.claude/agents/overseer.md` (4 merge sites + `:744` row), `.claude/agents/worker.md` (`:129`, `:156`), `CLAUDE.md` (item 5), `tests/framework/test_closing_guard_prose.py` (new: every overseer merge instruction names the wrapper and `sha`; no bare `{"merge_method":"squash"}` remains; rows and item 5 anchored): **4** | **Yes**: `.claude/agents/**`, `CLAUDE.md`. **CODEOWNER review** | S2 | — |
| **S4** | Post-merge detection. AD-8. | `scripts/framework/closing_guard.py` (`post-merge`), `.github/workflows/closing-keyword-postmerge.yml` (new), `tests/framework/test_closing_guard_postmerge.py` (new: attribution, idempotency marker, no-reopen, sanitize, read-failure red), `tests/framework/test_gate_checkout_pinned_base.py` (add workflow), `docs/LABELS.md`: **5** | **Yes**: `scripts/framework/**`, `.github/workflows/**` | S2 | **ESC-5**. `security-reviewer`, `reliability-reviewer` |

**Order.** S1 → S2 → S3, then S4 after S2.
- **Codable now:** S1 and S2. Every default they pin is either confirmed by evidence (AF-3) or one rule away from the alternative.
- **Between S1 and S2:** markers are written but nothing reads them. That is harmless.
- **Between S2 merging and activation:** CI is advisory (R-5).
- **Activation** (operator, ARCH-ESC-1) follows S3, so that the overseer's own path is guarded before branch protection starts blocking.

**Not touched by any slice:**
- `bootstrap/post_comment.sh` and `bootstrap/escalate_to_human.sh` (AM-1; no collision with #1928 S3, #1934 S2 or #2101);
- `scripts/automation/lib/merge_authority.py` (the not-a-meta-gate rule is a test, not an edit);
- `bootstrap/overseer-cron-prompt.md`.

### Test obligations (all deterministic: recording `gh` fakes, no network)

- **S1:**
  - The #1725 fixture through `edit_issue.sh` with no declaration → exit non-zero, no PATCH, stderr names `#1539` and the body line.
  - The same fixture with `--closes 1539` → one PATCH whose body ends with `<!-- hos-closes v=1 refs=1539 -->`.
  - `--title "fix: closes #42"` on a PR → refused.
  - The same body on an issue → applied unscanned.
  - `--closes` on an issue → usage error, zero network writes.
  - `--closes` alone on a PR → the marker is re-rendered with the union.
  - A caller body containing `<!-- hos-closes` → refused by both scripts.
  - Label-only edits → no GET of the item and no `python3` invocation (asserted by the recording fake).
  - `submit_pr.sh` with no `--closes` → the body sent ends with `refs=` (empty, not absent).
  - TD-1856 §10 tests pass unmodified apart from the module path.
  - `find_closing_refs(render_marker(K)) == []` for numeric and cross-repo K.
  - Duplicate or malformed markers → `Invalid`.
- **S2:**
  - Absent vs empty: no marker + `fixes #5` → fail; no marker + no refs → pass.
  - An untrusted author's valid marker → ignored.
  - A manual link (`closingIssuesReferences` only) → fail naming it.
  - A commit-message ref → fail.
  - A GraphQL error, a 404, a 250-commit page and `hasNextPage` → exit 2.
  - The workflow has `edited` in `types`, a base-SHA checkout, no `${{ …title/body/head.ref }}` in `run:`, and a job name equal to the context line.
  - `closing-keyword-guard` is not in `_META_GATE_CHECKS`.
  - The AF-5 envelope test.
  - The wrapper emits exactly one JSON object, carries `head_sha`, and never mints for `--help`.
- **S3:** the prose test (above).
- **S4:**
  - An undeclared closure attributed to the merge SHA → one comment + `needs-human`, and a rerun adds nothing.
  - A declared closure → no action.
  - No call to `PATCH issues/{n}` with `state` ever appears (no-reopen).
  - A read failure → non-zero exit.

---

## 5. Requirement amendments (for pm-agent to record; the requirements file is not edited here)

- **AM-1 (REQ-1, REQ-2, ESC-1; AF-2).**
  - The record moves from a trusted PR comment to exactly one marker line in the PR body: `<!-- hos-closes v=1 refs=… -->`.
  - It is honoured only on PRs authored by a HOS App or `HUMAN_REVIEWER`.
  - REQ-2's `post_comment.sh`/`escalate_to_human.sh` refusals are **withdrawn**. In their place, `submit_pr.sh` and `edit_issue.sh` refuse caller bodies that contain a marker line. The `updated_at == created_at` rule is withdrawn with the comment.
  - REQ-1's ACs stand, read from the body: `{12}`, `{}` and the union.
- **AM-2 (REQ-6).**
  - `--closes` on a PR is accepted alone, as well as with `--body-file`/`--title`.
  - The declaration is written **in the same PATCH** as the body, not after it.
  - The set is the union with the current valid marker.
- **AM-3 (REQ-1, AF-10).** `submit_pr.sh --update-pr` writes no record. `edit_issue.sh --closes` is the single amendment path after open.
- **AM-4 (REQ-7).**
  - Trigger types are `opened`, `edited`, `synchronize` and `reopened`, on base `main` only.
  - Re-evaluation on a new declaration comes from `edited`, not an `issue_comment` trigger. TD-O4 is answered by AD-5, with the probe-decided rerun fallback.
  - CI output is wrapped in a stop-commands envelope and sanitized (AF-5).
  - The check must not be classed as a meta gate.
  - The statement that REQ-7 "covers P2/P5" is qualified: it is **advisory for an admin merge** (AF-4).
- **AM-5 (REQ-8, ESC-3).**
  - (a) and (b) are withdrawn: no `commit_title`/`commit_message` is composed or sent.
  - (c) becomes "run `bootstrap/closing_guard.sh check` immediately before the PUT".
  - (d) stands: `sha` = the evaluated head.
  - The wiring covers **all four** overseer merge sites (AF-6).
  - ESC-3 is withdrawn as moot. The superset argument is in AD-3 and AD-6.
- **AM-6 (REQ-10, ESC-5).**
  - Detect and notify only: a comment on the closed issue plus `needs-human`, with no reopen (pending ESC-5).
  - The candidate set adds the merge commit's own message.
  - Attribution is by the `closed` event's `commit_id`, and ambiguity resolves toward notifying.
- **AM-7 (REQ-9).** The "read-only primitive" is `bootstrap/closing_guard.sh check` over `scripts/framework/closing_guard.py`. `overseer_merge.sh` later calls `closing_guard.evaluate` in-process.
- **AM-8 (REQ-11).** The grammar module moves to `scripts/framework/closing_keywords.py` (AF-1). The caller and remedy come from closed enums, and `submit_pr.sh`'s output is byte-identical.
- **AM-9 (REQ-12, AF-7).** `closing-keyword-refused` audit events are written for the local phases `edit` and `merge` only. For `ci` and `post-merge`, the durable records are the check run and job summary, and the issue comment and label.
- **AM-10 (§5 slices).** The slices are re-cut as §4: S1+S2 of the requirements merge into S1, and every agent and `CLAUDE.md` edit is collected in S3 so the human reviews it once.
- **AM-11 (TD-O1, TD-O3).** TD-O3 is answered: `edit_issue.sh` is not shipped. TD-O1 is answered provisionally: the squash default is title + blank body (AF-3), and S2 confirms it from repo settings. The design no longer depends on the answer.

Endorsed as written: REQ-3, REQ-5 (as specified in AD-4), REQ-13 (extended per AD-9 and AF-6), REQ-14 (extended per §4), and NG-1 to NG-6.

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **User-visible or operational, routed (not mine to sanction):**
  - **A new required check that can block every merge,** including the human's, until each closing reference is declared or rephrased. An admin can bypass it. This is pm ESC-6.
  - **Activation is an operator obligation** (ARCH-ESC-1):
    - register `closing-keyword-guard` wherever this repo's live required checks are enforced (ruleset and/or classic; AF-9);
    - beforehand, make sure every open PR has a run of the new check. A required context with no run stays "expected" and blocks, the #737 mode. Any `edited` or `synchronize` event produces one.
  - **The human's declaration recipe changes** from "post a comment" (pm default) to "add or edit one line in your PR body" (ESC-1 restated).
  - **The post-merge job labels issues `needs-human`** and comments on them as `github-actions[bot]` (ESC-5).
- **Cost.** Two short `pull_request_target` jobs per PR event, about 3 to 5 API reads each. One read-only wrapper call per overseer merge. No new service and no new credential. The new trust boundary is S4's `issues: write` job, which is security-reviewed.
- **Data retention.** None new. The marker is public PR text, and audit events stay in the existing local stream.
- **Startup gap: yes, in my own #1856 review.**
  - TD-1856 §11a approved placing the guard's grammar on unprotected surface (AF-1). An overseer-mergeable PR could have weakened `submit_pr.sh`'s guard at any time since #1856 merged.
  - **Recommendation to the worker:** open or annotate a `startup-artifact-gap` issue against #1856/#2047. I have not filed it, per this task's instructions.
- **Affected sign-offs.**
  - **#1856 code sign-offs on `closing_keywords.py` logic stand.** The logic is unchanged and its tests carry over.
  - **The TD-1856 §4 placement and my §11a "path is sound" approval are superseded** for placement only. They are re-reviewed in S1 by `security-reviewer`.
  - **The `submit_pr.sh` #1856 sign-off is re-reviewed in S1** (marker append, path change).
  - **The `edit_issue.sh` #1204/#1312 sign-offs are re-reviewed in S1** (new PR path; the label path is asserted unchanged).
  - **The #1299/#972 gate-workflow sign-offs stand.** No existing gate workflow is edited unless the probe forces the dispatcher fallback, which would re-review `rerun_gate_checks.py`'s.
  - **ADR-1357 AD-5 and AD-7 stand.** FU-1 adds one in-process call to slice 4's design.
  - No other approved design or code is orphaned.

---

## 7. Open human escalations

pm-agent's ESC-1 to ESC-7, with the architect's positions:

| ESC | Architect | Note | Gates |
|---|---|---|---|
| ESC-1 | **Restated; recommend the body marker (AD-1)** over the pm default (comment) | Comments race `opened` (AF-2), need an `issue_comment` trigger with #1299 history, and need two more protected-script refusals. Same forge resistance. Under the pm default: AD-1's writers post a comment instead, AD-5 adds an `issue_comment`-driven in-place rerun via `rerun_gate_checks.py`, and AM-1's refusal list reverts to REQ-2's | S1 |
| ESC-2 | **Concur, refined:** only the CODEOWNER's own PRs (and HOS Apps') can declare; other authors and forks must remove closing text | Editing someone else's body needs write access, so author-trust bounds editors | S1 |
| ESC-3 | **Withdrawn (moot)** | AD-6: no composed message; the superset scan plus the `sha` pin | — |
| ESC-4 | **Concur:** build now, wire into prose (S3); slice 4 calls `evaluate()` in-process | FU-1 | S3 |
| ESC-5 | **Recommend (b): comment + `needs-human`, never reopen** | Reopen overrules the trust root and re-exposes the issue to worker selection. (a) adds one `PATCH state=open` and flips the no-reopen test. (c) defers S4 entirely and leaves P4 undetected | S4 |
| ESC-6 | **Concur: required, HOS-only** | Advisory leaves the overseer guarded by AD-6 alone and the human by AD-8 alone | S2 merge |
| ESC-7 | **Concur: out of scope** | — | — |

Architect item (tier `hard-tradeoff`):

- **ARCH-ESC-1 (activation timing for the required check).**
  - **(a)** Activate after S3 merges, the S2 probe passes, and **5 consecutive real PRs** show `closing-keyword-guard` green or correctly red.
  - **(b)** Activate as soon as S2 merges.
  - **(c)** Never activate; advisory plus AD-6 plus AD-8.
  - Consequence of (b): the overseer path is blocked by branch protection before its prose knows why. The bounce gate would route failures to the worker, but the window is unguarded on false refusals.
  - *Recommended: (a).*

```yaml
adr: ADR-2047-2048
issues: [2047, 2048]
codable_now: [S1, S2]
design_now_merge_after: {S2: [S1, ESC-6, "supersession probe (ii) blocks"], S3: [S2], S4: [S2, ESC-5]}
operator_steps: ["activate closing-keyword-guard per ARCH-ESC-1 (ruleset/classic, AF-9)"]
hard_constraints_not_waivable: [AD-2 protected grammar, AD-3 absent-is-not-empty, AD-5 live-reads + stop-commands envelope, "AD-6 no clean JSON -> no PUT"]
not_touched: [bootstrap/post_comment.sh, bootstrap/escalate_to_human.sh, scripts/automation/lib/merge_authority.py, bootstrap/overseer-cron-prompt.md]
escalations:
  - {id: ESC-1, tier: hard-tradeoff, options: {body-marker: AD-1, comment: pm-default}, recommended: body-marker, gates: [S1]}
  - {id: ESC-2, tier: hard-tradeoff, recommended: "CODEOWNER-authored + App-authored PRs only", gates: [S1]}
  - {id: ESC-3, status: withdrawn}
  - {id: ESC-4, recommended: build-now, gates: [S3]}
  - {id: ESC-5, tier: hard-tradeoff, options: {a: reopen, b: notify-only, c: defer}, recommended: b, gates: [S4]}
  - {id: ESC-6, tier: hard-tradeoff, recommended: required-hos-only, gates: [S2]}
  - {id: ESC-7, recommended: out-of-scope}
  - {id: ARCH-ESC-1, tier: hard-tradeoff, options: {a: after-S3-and-5-PR-soak, b: on-S2-merge, c: never}, recommended: a, gates: [activation]}
```

---

## 8. Notes and follow-ups (named, not filed here)

- **FU-1 → #1357.** TD-1357 slice 4: `overseer_merge.sh`'s AD-5 recompute calls `closing_guard.evaluate()` in-process, refuses on non-clean, and sends `sha`. The S3 prose then drops the separate wrapper call.
- **FU-2 → #1538.** TD-1538's writer inventory (`:94`, `:976`) omits `submit_pr.sh:_hos_audit_closing_keyword_refusal` (#1856) and, after S1, `edit_issue.sh`'s refusal helper. Both should migrate to `audit_append` in the same slice as `stale-base-merged`. Also, TD-1538's planned `pr-opened` event (`:922`) sits next to AD-7's marker append in `submit_pr.sh`. Whichever merges second rebases. There is no semantic conflict.
- **FU-3 → pm-agent.** `scripts/automation/**` holds other inputs to gating decisions, including `merge_authority.py` and `merge_config.py`, on unprotected surface. AF-1 is one instance of a class that #1574 or #1935 (surface classification) should own.
- **FU-4 → pm-agent (R-3).** The overseer's between-cycle merge audit (`overseer-cron-prompt.md:28-36`) could also report a failed `closing-keyword-postmerge` run for each PR merged in the window.
- **N-1.** The human uses merge commits and rebase merges (AF-3). The guard does not need squash-only, and this ADR does not recommend changing merge methods. If the human ever restricts the repo to squash-only, commit scanning in CI becomes conservative rather than load-bearing, and nothing else changes.
- **N-2.** The task framing asked whether the declared-closes record should be a PR comment. AD-1 answers no, for the AF-2 reasons. The deciding fact is that the record must exist atomically with the PR.

## Escalation flag (CORE self-flag)

RISK: MEDIUM-HIGH.
- The design adds a required check that can halt every merge, a write-capable `pull_request_target` job, and new behaviour on the shared `edit_issue.sh` path.
- A fail-open defect re-exposes the #1725 class (silent closure of a `priority:critical` issue).
- A false-refusal defect blocks merges until it is fixed.

CONFIDENCE:
- HIGH on §0: every citation was read in this session, and AF-3's merge-method evidence comes from `git log` on `origin/main`.
- HIGH on AF-1 and AF-5.
- MEDIUM on GitHub semantics that S2 must probe:
  - newest-run supersession for `edited`;
  - whether `closingIssuesReferences` reflects title or commit keywords (TD-O2; the design reads both sources regardless);
  - `closed`-event `commit_id` attribution for body-keyword closures.

BLAST RADIUS:
- every PR into `main` (S2, once activated);
- every agent title or body edit on a PR (S1);
- every overseer merge (S3);
- issues closed by merges (S4: label and comment only).

Change classification: STRUCTURAL.

## Human Review Required

- **ESC-1 (restated: body marker vs comment)** and **ESC-2** before S1 merges.
- **ESC-6** before S2 merges.
- **ESC-5** before S4 merges.
- **ARCH-ESC-1** before anyone activates the required check. Activation is your operator act, in whichever mechanism (ruleset or classic) this repo enforces.

S1 and S2 may be built and reviewed now. AD-2, AD-3, AD-5's live-read and stop-commands rules, and AD-6's "no clean JSON, no merge" are not open to any answer. Every slice is a protected-surface PR, and your own-account approval is the final gate.
