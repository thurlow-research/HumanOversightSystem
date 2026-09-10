# PRELIMINARY REQUIREMENTS — Script coverage for sandboxed Worker & Overseer

> **STATUS: PRELIMINARY REQUIREMENTS — NOT DIRECTLY ACTIONABLE.**
> This document is *input* to the spec crew (pm-agent → architect →
> technical-design). It is an investigation product: an inventory of what the
> autonomous Worker and Overseer actually do, mapped against the existing
> script inventory, with the gaps outlined as candidate scripts. Nothing here
> is a final design. Script names, granularity, and language choices are
> proposals for the spec crew to accept, merge, split, or reject. Do not
> implement from this document.

Date: 2026-09-10
Author: human-proxy session (investigation requested by ScottThurlow)
Tracking issue: #1542
Related: #1146 (sandbox extension to worker/overseer), #1216 (deterministic
checks → CI), #1155 (`python3 -c` unallowlistable), #967 (branch ownership),
#1213 (search-before-tooling), `docs/SANDBOX-POLICY.md`,
`scripts/framework/gen_sandbox_config.py` (currently refuses
`--role worker|overseer` with `EXIT_UNSUPPORTED_ROLE`, pending #1146).

---

## 1. Problem statement

Today both autonomous roles run with **no permission gate**
(`docs/SANDBOX-POLICY.md` §2, verified 2026-08-01):

| Path | Launcher | Posture |
|---|---|---|
| Interactive worker/overseer | `bin/hos-worker` / `bin/hos-overseer` | `--dangerously-skip-permissions` |
| Autonomous cron (both) | `bin/hos-cron` | `--permission-mode bypassPermissions` |

We want to move both roles into the sandbox + allowlist model already proven
for the Human role. The failure mode we must design against is **silent
denial**: in a headless `claude --print` session there is no prompt UI — an
unallowlistable command is denied outright, the denial is reported to the
model, and the cycle continues **having silently skipped that step**
(measured 2026-08-01, Test B, #1146: exit 0, not a hang).

A command is allowlistable only if its full text is statically matchable.
Command substitution `$(…)`, heredocs, `$VAR` expansion, loops, backslash
continuations, `source` of runtime-named files, and `&&`/`;` chaining of
unrelated steps all defeat matching (CLAUDE.md → "Shell usage under the
sandbox"). Therefore: **every action either role takes in autonomous mode
must be expressible as a single invocation of a committed script (or an
already-allowlistable simple command).** This document inventories those
actions and outlines the missing scripts.

Language convention requested by the operator: **Python for complex logic,
with thin shell wrappers where a shell entry point is needed; plain shell for
simple operations.** This matches the existing direction (SPEC-331…338 moved
decision logic shell → Python).

## 2. Scope and method

Sources reviewed exhaustively:

- `.claude/agents/worker.md` (full CORE region, incl. NG3b release protocol)
- `.claude/agents/overseer.md` (full CORE region, incl. merge-authority flow)
- `bootstrap/worker-cron-prompt.md`, `bootstrap/overseer-cron-prompt.md`
- `bin/hos-cron` (launcher — what is pre-computed *outside* the session)
- `SCRIPTS-INDEX.md` + live listings of `bootstrap/`, `scripts/**`,
  `scripts/automation/lib/`
- `docs/SANDBOX-POLICY.md`, `scripts/framework/gen_sandbox_config.py`
- CLI-surface check of the Python libs (which have `__main__`, which don't)

**In scope:** every Bash-tool command the worker or overseer issues in
AUTONOMOUS mode, including commands their own docs currently instruct them to
run raw.

**Explicitly noted but deferred (§9):** the command surface of the *dispatched
specialist subagents* (coder, reviewers, test agents). They run inside the
same sandboxed session and need the same treatment, but their surface is
mostly already script-shaped (test runners, validators, gates); a per-agent
pass is follow-on work for the spec crew.

**Not in scope:** `bin/hos-cron` itself. The launcher is a cron shell script
running *outside* the Claude session; permission rules never apply to it. Its
pre-computed context (NEW WORK directive, actionable-PR preamble, candidate
lists, release-request lists) is a major mitigation already in place — the
agents should keep leaning on it rather than re-deriving.

## 3. What is already covered (no new scripts needed)

The wrapper family is strong on the **issue** side and on **local
test/validation** execution. These existing entry points cover their listed
operations and need at most flag-level enhancement:

| Operation | Existing entry point |
|---|---|
| Auth / token mint | `bootstrap/get_app_token.sh` (launcher does this pre-session) |
| Token revoke | `bootstrap/revoke_app_token.sh` |
| Issue reads (single/list/comments/milestones/assignable) | `bootstrap/query_issues.sh` |
| Issue create | `bootstrap/create_issue.sh` |
| Issue/PR metadata + body edits, labels, milestone, state, assignees | `bootstrap/edit_issue.sh` |
| Plain comment | `bootstrap/post_comment.sh` |
| Resolvable review thread | `bootstrap/post_review_thread.sh` |
| Branch creation (+ ownership record) | `bootstrap/create_branch.sh` |
| PR open / update-push (incl. merge-from-base guard #1162) | `bootstrap/submit_pr.sh` |
| Repo sync | `bootstrap/hos_repo_sync.sh` |
| Inner-loop tests | `scripts/framework/run_tests_inner_loop.sh` |
| Full/release tests | `scripts/framework/run_tests.sh`, `run_tests_release.sh` |
| Gates | `scripts/oversight/run_gates.sh` |
| Validators | `scripts/oversight/run_validators.sh` |
| Second review / review chain | `scripts/run_second_review.sh`, `scripts/run_review_chain.sh` |
| Agent static check | `scripts/framework/check_agents_static.sh` |
| Release cut (human-authorized, verbatim command) | `scripts/framework/cut_release.sh` |
| Stale-commit pre-PR guard | `scripts/automation/pre_pr_stale_check.py` (has CLI) |
| PR-review idempotency precheck | `scripts/oversight/check_pr_reviewed.sh` |
| Post-change sweep | `scripts/framework/run_post_change_sweep.sh` |
| Smoke test | `scripts/oversight/smoke_test.sh` |

Simple, prefix-allowlistable raw commands that can stay raw (candidate
allowlist rules, spec crew to confirm): `git status --short`, `git fetch
origin`, `git log …`, `git diff --stat …`, `git rev-parse …` *as standalone
reads whose output the model consumes directly* (not as `$(…)` inside another
command — that is the distinction that matters).

## 4. Gap inventory — GitHub **PR read** operations (largest gap family)

Both role docs literally annotate several operations "no wrapper yet." Every
one of these appears in the autonomous loops:

| # | Operation | Where used | Today's (unallowlistable or raw) form |
|---|---|---|---|
| R1 | PR detail: head SHA, `mergeable_state`, draft, labels, author, `requested_reviewers`, milestone | worker Step 1 + conflict path; overseer steps 3, 5 (`head_sha` for `check_pr_reviewed.sh`, freshness #1251) | `gh api repos/{o}/{r}/pulls/N --jq …` |
| R2 | PR reviews list (state, `commit_id`, reviewer login, review id) | worker CHANGES_REQUESTED path; overseer #589/#741/#1251 human-approval checks, batch-merge re-check §6b | `gh api …/pulls/N/reviews` — "no wrapper covers PR review reads yet" (worker.md) |
| R3 | PR changed files + commit count | overseer size check §3a; worker PR-size self-check (≤15 files/10 commits) | raw `gh api` / `gh pr view` |
| R4 | Open-PR list (optionally filtered to author) | worker Step 1 fallback; overseer preamble fallback | raw `gh api …/pulls?state=open` |
| R5 | Recently-merged PRs **with `merged_by`** (requires per-PR detail endpoint — list endpoint always returns `merged_by=null`, #758) | overseer Step 0 between-cycle merge audit | a literal `for … $(gh api …)` loop **in the cron prompt** — unallowlistable by construction |
| R6 | Issue **events** (`assigned`/`labeled`/`unlabeled` with `actor`/`assignee`/`assigner` logins and timestamps) | worker NG3b R5 three-signal verification; overseer C3 checks | raw `gh api …/issues/N/events` |
| R7 | Repo labels list | overseer operations protocol (label-convention detection) | raw `GET /repos/{o}/{r}/labels` — "no wrapper covers this read" (overseer.md) |
| R8 | Head-commit committed-at timestamp | overseer #902 hold-directive detection | raw `GET /commits/{sha}` |

**Candidate requirement:** one read-side wrapper for the PR namespace —
either a new `bootstrap/query_pr.sh --app <role> --pr <N>
(--detail | --reviews | --files | --list [--author <login>] | --merged-recent
[--hours 2] | --events <issue#> | --labels | --commit <sha>)` or extension of
`query_issues.sh`. Spec-crew decision: one script vs. two (issue vs. PR
namespaces), but the operations above are the required coverage either way.
Should be built on `scripts/automation/lib/github.py` (retry/backoff already
implemented — do not re-implement, #1213). Output: stable JSON to stdout so
the model consumes results without `--jq` expressions in the command line.

Enhancement to an existing wrapper: `query_issues.sh --comments N` is often
followed by a marker grep (e.g. `<!-- hos-worker-merge-block -->`,
`<!-- hos-ng3b-awaiting -->`, `Authorization required:` + SHA matching).
Piping wrapper output into `grep` re-introduces compound commands. Candidate:
`--comments <N> --contains <literal>` (and `--author <login>`) flags so the
match happens inside the wrapper.

## 5. Gap inventory — GitHub **PR write** operations (overseer)

All currently documented as raw API calls ("no wrapper yet — use
`PUT /repos/...`"). Each needs a canonical wrapper with the same
mint/act/revoke + identity-guard pattern as `create_issue.sh`:

| # | Operation | Where used | Notes for spec crew |
|---|---|---|---|
| W1 | Approve PR (POST review, `event=APPROVE`, canonical body) | overseer AUTO_MERGE step (1) | Overseer-only. Consider requiring a decision artifact (see §7/D1) as input so the wrapper can refuse an approval with no recorded matrix decision. |
| W2 | Merge PR (PUT merge, `merge_method=squash`) | overseer AUTO_MERGE step (2) | Overseer-only. Must confirm merge result; on failure the caller posts + labels. Serialization protocol §6b stays in the agent/orchestration layer, but the wrapper could enforce "re-read approvals immediately before merge." |
| W3 | Request reviewer (POST `requested_reviewers`) | overseer CRITICAL-tier path | Idempotent by API semantics; safe to run every cycle. |
| W4 | Dismiss a review (PUT `reviews/{id}/dismissals` + reason) | overseer #902 human-hold path | Needs review id from R2. |
| W5 | Convert PR to draft / ready | `record_pr_bounce()` finalization | Verify whether the Python path already performs this; if the agent ever does it from shell, it needs a wrapper (GraphQL mutation). |

Design principle for all write wrappers: **least privilege per script** — one
operation per wrapper, `--app <role>` identity guard inside the script,
`--body-file`-only for any free text, loud stderr, non-zero exit on any
partial failure. This is what makes the allowlist rules narrow
(`Bash(bash bootstrap/merge_pr.sh *)`) instead of `Bash(gh api *)`, which
would amount to arbitrary authenticated API.

## 6. Gap inventory — Python library logic with **no CLI entry point**

`#1155` already established that `python3 -c "…"` one-liners are
unallowlistable. Verified: of `scripts/automation/lib/*.py`, only
`pr_readiness.py` and `cycle_log.py` have `__main__` blocks. Yet the role
docs instruct the agents to *call library functions* throughout. Every
function below needs either a `python -m` entry point or a thin `.sh` wrapper
(spec crew to standardize one convention):

**Worker per-task chain:**

| # | Function(s) | Worker step |
|---|---|---|
| P1 | `correlation.py:already_exists` (idempotency precheck / resume state) | step 1 |
| P2 | `breakers.py:is_poisoned`, `record_task_failure` | step 2 (+ overseer step 2) |
| P3 | `claim.py:claim` / release / heartbeat | steps 3, 4, 10 |
| P4 | `triage.py:triage` | step 6 |
| P5 | `budget.py:BudgetGate` estimate/decide | step 7 |
| P6 | `envelope.py` emit/parse (claim + release envelopes) | steps 3, 10 |
| P7 | `ledger.py` append run/cost record | terminal |

**Overseer decision chain:**

| # | Function(s) | Overseer step |
|---|---|---|
| P8 | `merge_authority.py:detect_server_side_gate` | step 4 |
| P9 | `merge_authority.py:check_register_completeness` | step 4a |
| P10 | `merge_authority.py:decide_merge_authority` (with `reviews`, `head_sha`, `requested_reviewers`, `prior_overseer_decision`, `human_hold_directive`) | step 5 |
| P11 | `merge_authority.py:detect_human_hold_directive` | step 5 (#902) |
| P12 | `merge_authority.py:touches_protected_surface`, `has_human_approval` | pre-matrix gate #1325 |
| P13 | `merge_authority.py:record_pr_bounce` | step 4a/4b |
| P14 | `scripts/oversight/codeowners.py:check_pr_files` (has `__main__`? verify — SPEC-303b gate) | pre-matrix CODEOWNERS gate |

**Candidate requirement (preferred shape, for spec-crew evaluation):** rather
than 10+ micro-CLIs, a single **overseer decision CLI** — e.g.
`scripts/oversight/overseer_decide.py --pr <N>` — that performs the full
deterministic pre-decision pipeline internally (fetch PR detail/reviews/
comments via `github.py`; run size check, CODEOWNERS gate, protected-surface
gate, register completeness, out-of-scope-commit scan, validator-artifact
check, matrix with all #589/#741/#761/#902/#1251 parameters) and emits one
JSON decision record with per-gate evidence. The agent then *acts* on the
decision (post/approve/merge/escalate via the §5 wrappers) but never
re-derives it. This directly implements the #1216 direction (deterministic
checks out of the model) and collapses the largest cluster of
unallowlistable calls in the system. The worker-side analog is smaller
(P1–P7 are already discrete steps; micro-CLIs may be fine there).

## 7. Gap inventory — compound git / release / audit operations

| # | Candidate script | Replaces (currently unallowlistable) | Used by |
|---|---|---|---|
| G1 | `commit_with_trailers` — `--message-file <path>` + enforced trailer set (`Prompt-Artifact`, `AI-Model`, `AI-Risk`, `Supervised-by`); refuses missing trailers | heredoc/multi-line `git commit -m "$(…)"` | worker (and coder subagent) on every commit |
| G2 | `validator_artifact_check` — the full §3b ancestry algorithm (artifact commit lookup, `head_sha == parent`, ancestor check, PR-scoped staleness diff with exempt paths, schema check) → JSON verdict | five chained git commands with `$(…)` substitutions | overseer step 3b |
| G3 | `run_pr_readiness` wrapper (or `--base-sha auto --head-sha auto` on `pr_readiness.py`) — derive SHAs internally | `python -m … --head-sha $(git rev-parse HEAD)` | worker step 8.9 |
| G4 | `release_tier` — last tag, semver bump class, PATCH-promotion rule (diff-since-tag vs. promoted paths) → tier + required-suite list. May extend `release_logic.py` (CLI exists but takes `--tag`/`--local` as caller-supplied values — i.e. still needs substitution to feed; make it self-deriving) | `git describe --tags` + hand-applied table | worker R2 |
| G5 | `release_auth_status` — NG3b R1 trigger validation (title/label/state/`Command:` line/R1.5 creator-vs-BOT_ACCOUNTS) **and** R5 verification (current-state conditions, authorizing self-assignment event shape checks, three-signal same-actor check, CODEOWNERS membership, `T_comment` ordering, HEAD binding) → JSON: `AWAITING | AUTHORIZED | VIOLATION(<failed_check>)` + evidence | the most intricate prose-only protocol in the system; today requires many raw event reads + hand evaluation every cycle | worker R1/R5 |
| G6 | `compose_release_comment` — build the R3/R4 results-comment body file (suite results incl. carry-forward restatements, fenced `git log <tag>..HEAD`, `git status --short`, `Release candidate SHA:` line, `Command:` line, How-to-authorize block) → writes body file for `post_comment.sh` | agent-composed body via redirects of `$(…)` output | worker R3/R4 |
| G7 | `check_recent_merges` — closed-PR sweep resolving `merged_by` via detail endpoint, windowed (default 2h) → JSON lines | the literal `for pr in $(gh api …)` loop in `overseer-cron-prompt.md` Step 0 | overseer Step 0 |
| G8 | `audit_query` — standalone read: `--event <name> [--match '"pr":<n>' …]`, generalizing `check_pr_reviewed.sh`; loud stderr | `source scripts/oversight/lib/audit_log.sh` + `audit_read_stream \| grep -F … \| grep -F …` (source+pipe chain) | overseer idempotency prechecks (#849 family: human-authorized-merge, pr-merged-without-review, release-gate-validation); worker NG3b |
| G9 | `audit_append` — standalone write: `--event <name> --json-file <path>` (or typed flags) wrapping `audit_write_event` | `source … && audit_write_event '{…}'` | both roles, every audited action |
| G10 | `check_identity` — `--expect worker\|overseer\|human`, exits non-zero on mismatch | `[ "$HOS_BOT_LOGIN" = "…" ] \|\| exit 1` ($VAR expansion) | both cron prompts' identity guard |
| G11 | `next_candidate` — wraps the milestone+`needs-ai` query through `next_candidates.jq` | fallback `gh api … --jq "$(cat scripts/automation/lib/next_candidates.jq)"` (substitution) | worker Step 2 fallback |
| G12 | `rebuild_pr_branch` — the worker Step 1 "dirty PR" conflict recovery: identify unique commits, `create_branch.sh` from current main, cherry-pick, force-push to same remote branch name (in-place PR update) | a multi-step git sequence currently described in prose, incl. a force-push path that bypasses `submit_pr.sh` (known residual gap noted in CLAUDE.md §Submitting a PR) | worker Step 1 |
| G13 | Out-of-scope-commit helper (SPEC-328 Option A): revert on PR branch, create `fix/<cid>-out-of-scope-<sha8>` from target, cherry-pick — possibly as a guided script | raw `git revert`/`git cherry-pick`/branch dance | worker bounce response |

Also verify during spec: `scripts/oversight/release_artifact_logic.py` (has a
CLI) fully covers the overseer's #695 release-gate deep validation from shell,
including the `git show origin/main:…` artifact reads — if yes, the cron
prompt should invoke it by name instead of describing the procedure.

## 8. Cross-cutting requirements (apply to every script above)

1. **Single invocation, literal args.** Every script must be fully drivable
   as `bash <path> --flag value …` with literal values; anything long goes in
   a `--…-file` argument. No script may *require* the caller to compose
   `$(…)`, pipes, or env-var arguments.
2. **Self-deriving context.** Wherever today's usage forces the caller to
   substitute a value the repo already knows (HEAD SHA, last tag, repo slug,
   milestone number), the script derives it internally. This is the root fix
   for most substitution patterns.
3. **Identity guard inside the wrapper** (`--app <role>` pattern), never in
   the caller's shell.
4. **JSON to stdout, diagnostics to stderr, never suppress stderr** (#1533 /
   `check_pr_reviewed.sh` convention). Exit codes: 0 = answered (caller
   decides), 2 = usage, distinct codes for distinct failures (the
   `gen_sandbox_config.py` convention).
5. **No secrets on stdout/argv.** Token flows stay inside
   `get_app_token.sh`-pattern scripts (#1086, #734).
6. **Idempotent or precheck-paired.** Any write that a rolling window can
   re-trigger (the #849 class) must either be idempotent or ship with its
   read-side precheck in the same script.
7. **Tests + SCRIPTS-INDEX.** Each script lands with tests (the repo rule:
   "second time you need it, it belongs in `scripts/` with a test") and a
   `regen_all.sh` run.
8. **Prompt updates are part of the work.** `worker-cron-prompt.md`,
   `overseer-cron-prompt.md`, `worker.md`, and `overseer.md` currently embed
   the raw forms (including a literal `for` loop and `${MILESTONE}`
   expansion). Each new script must replace its raw form in those documents
   in the same change, or the agents will keep emitting the unallowlistable
   version.
9. **Allowlist deliverable.** The end state is a generated
   worker/overseer sandbox policy (`gen_sandbox_config.py --role worker|
   overseer`, currently refused pending #1146) whose Bash allowlist is
   essentially: the wrapper scripts by literal path, the test/validator/gate
   runners, and a short list of read-only git commands. The spec should
   enumerate that rule set explicitly as an artifact.
10. **Failing safely stays the rule.** Scripts fail loud and exit; agents
    report and stop. No script should paper over a denial by retrying
    alternate paths.

## 9. Follow-on scope the spec crew should plan (not covered here)

- **Specialist-subagent command surface.** coder, reviewers, unit-test,
  system-test, risk-assessor et al. run in the same sandboxed session.
  Their surface is mostly the already-covered runners, but coder's git usage
  (add/commit) hits G1, and risk-assessor invokes validators with
  changed-file lists (check how those lists are passed). A per-agent audit
  pass is needed.
- **Granularity decision for §6:** one orchestrating decision CLI vs. many
  micro-CLIs — trade auditability of a single decision record against
  composability. (Recommendation embedded in §6: single CLI for the overseer
  decision chain; micro-CLIs for the worker task lifecycle.)
- **Read-wrapper policy:** whether a narrowly-scoped generic GET wrapper is
  acceptable for the long tail of one-off reads, or every read gets a named
  flag on `query_issues.sh`/`query_pr.sh`. Current repo philosophy (#1213,
  "one invocation site") favors named operations.
- **#1216 interaction:** several overseer checks are slated to move to CI.
  Scripts built for §6/§7 should be CI-invocable from day one so that
  migration is a relocation, not a rewrite.
- **Interactive-mode parity:** the same scripts remove prompt friction in
  interactive sessions; no separate work needed, but the docs' "no wrapper
  yet" annotations should be swept once wrappers land.

## 10. Summary counts

- Existing entry points confirmed sufficient: **~20** (issue-side GitHub
  wrappers, test/gate/validator runners, branch/PR lifecycle wrappers).
- Gap families identified: **4** — PR-namespace reads (8 operations),
  PR-namespace writes (5 operations), library-logic CLI exposure
  (14 functions), compound git/release/audit operations (13 candidate
  scripts).
- Documents requiring coordinated edits when scripts land: **4**
  (both cron prompts, both agent CORE regions) plus `CLAUDE.md`'s canonical
  entry-point table and the sandbox policy template.
