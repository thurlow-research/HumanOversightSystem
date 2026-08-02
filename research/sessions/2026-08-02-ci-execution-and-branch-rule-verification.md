# Session: Verifying the Branch Rules, and Finding Nothing Executes the Tests

**Date:** 2026-08-02
**Role:** Human-proxy orchestrator (interactive), Human clone
**Duration:** ~2 hours
**Artifacts:** 5 issues filed (#1213, #1214, #1216, #1217, #1218), 1 closed (#1203), 3 issues commented, 1 design handoff reviewed

---

## What this session was

A verification pass that started as a narrow request — confirm the newly-added
`require_last_push_approval` rule is in effect — and repeatedly found that the thing being
verified was not the thing that mattered.

The branch rules were correct. The checks they require turned out not to analyse code. The
gate substituting for that analysis turned out to be ignored by instruction. Each answer
was reached by running a command; none by reading configuration.

---

## What was verified

**The ruleset is as intended.** `main-protection` (active, `refs/heads/main`, updated
2026-08-02 17:16 UTC) carries `require_last_push_approval: true`,
`required_review_thread_resolution: true` (the #1206 fix), 1 approval,
`require_code_owner_review`, `dismiss_stale_reviews_on_push`, deletion and
non-fast-forward blocked, and three required checks.

**Classic branch protection returns 404.** Protection is implemented as a ruleset, so
`GET /branches/main/protection` answers `Branch not protected` — a confidently wrong answer
to a reasonable check. (Already recorded in the prior session; re-encountered immediately.)

**The bypass actor is intended.** One `User` actor with `bypass_mode: always`, confirmed by
the human as correct — himself, maintainers, admins.

---

## The through-line: three layers, none of them executing

Asked whether branches should be required up-to-date before merging
(`strict_required_status_checks_policy`), the intuitive answer is yes. Working out why it
would buy nothing exposed the actual gap.

1. **Two of the three required checks are approval gates**, not code analysis. Re-running
   them against a moved base yields the same answer.
2. **The third reads a committed artifact**, which the overseer had already flagged as
   stale against PR HEAD (#1170).
3. **No workflow runs the test suite at all.** Grepping every workflow for `pytest`,
   `unittest`, `run_gates`, `run_validators` returns nothing, against substantial suites.
4. **The overseer is forbidden from re-running them** — `overseer.md:60`, under "These are
   hard limits. No override path."
5. **The attestation's consumer is instructed to disregard it** — `overseer.md:391` calls
   stamp checks a known false positive "until the content-hash redesign (#552) ships." #552
   closed 2026-06-28, five weeks earlier. The gate itself is live and was confirmed failing
   for real on PR #1210 (#1211); it is the instruction that is stale, which is a latent risk
   rather than a bypass already taken.

So between authoring and merge, nothing independently executes the tests, and the gate that
records they were run is one an agent has been told in advance to dismiss.

The human's framing settled the design question: re-running on a moved base is redundant
*because the required checks don't analyse the merged code* — and the fix is to move
execution into CI, where a failing PR never reaches the overseer at all. In an agentic
pipeline the reviewer is an LLM, so shift-left is simultaneously the safer and the cheaper
option; the usual tradeoff does not apply because the expensive stage is judgment, not
compute.

---

## Key decisions and the reasoning behind them

**Python over bash for the read wrapper — but not for the reason proposed.** The human
asked whether the wrappers had enough embedded logic to warrant Python for testability.
Measured: they are thin (89 and 158 lines) and *already* well tested — 568 lines of pytest
running the real scripts against stubbed `git`/`gh`/`curl` on `PATH`. Bash-is-untestable was
false here. Python won on a different ground: `lib/github.py` already implemented the reads
with retry and rate-limit handling, so a bash version would have been a second GitHub path
lacking it.

**Named subcommands, not an API passthrough.** A consequence of the above: read-only
enforcement becomes an allowlist rather than the denylist originally specified ("reject
non-GET").

**No rewrite of the write wrappers.** `lib/github.py` has no create paths, so
`create_issue.sh`/`submit_pr.sh` are not duplicating it — they implement what it lacks. Add
a capped retry in place (#1218) rather than rewriting tested code on the autonomous
critical path.

**`strict_required_status_checks_policy` considered and rejected.** It would re-run two
approval gates and an artifact read, at the cost of serialising a cron-driven PR queue.

**Do not hand-enumerate scripts in CLAUDE.md.** `bootstrap/` is 8-of-9 accurate;
`scripts/` has ~40 unlisted. Hand-enumeration works at 9 items and has already failed at 60.
A partially-stale index is worse than none — it implies "not listed = does not exist,"
which is the inference that produced the duplicate-wrapper issue in the first place.

---

## Surprises

**The gap I filed an issue about closed while I was filing it.** `bootstrap/post_comment.sh`
merged at 17:37, mid-session, having been absent from a clone 15 commits behind. The issue
asserting no comment wrapper existed was wrong before it was submitted — and the merge
created the exact duplication the issue existed to prevent (`post_comment.sh` in bash
without retry, `lib/github.py::post_comment` in Python with it).

**A design handoff's own method warning did not protect it.** The desktop design document
for #1202 closed by advising re-measurement rather than inheriting prior observations, and
listing five earlier conclusions that had proved to be artifacts. Its own Correction 1
asserted a deny rule had been removed; the file was unmodified since twelve hours before the
document was written, and a direct probe confirmed the rule still in force. Its central
argument — that removing the rule re-opened an escalation path — described something that
never happened.

**The irreducible blocker is not irreducible for the proposed mechanism.** The
`.claude/settings.json` bind mount is real and unconfigurable, but exists in the sandbox's
mount namespace. Today's pull modified that exact file, plus all 34 previously-failing
paths, from an ordinary shell *while a sandboxed session was live*. Cron runs outside the
sandbox, so the blocker does not block cron sync at all.

**The repair runbook expired during the repair.** #1203 specified `expect c17f20f or later`;
`main` advanced 15 commits to `9ef0d13` while the issue sat.

**Steps 1–3 of that runbook had already discarded the one edit worth keeping.**
`git checkout -- .` took the `.envrc` fix along with the pull artifacts.

---

## Learnings about the methodology

**Every correction this session came from running a command; none from reading
configuration or documentation.** Four separate confidently-written claims were falsified —
three of them mine, one in a document warning against exactly that failure. The asymmetry is
strong enough to be a rule: state claims are cheap to assert and cheap to check, and the
checking is not happening.

**Existence checks need a named reference.** "X does not exist" was wrong twice today, from
two different causes — not searching (`lib/github.py` was present locally) and searching a
stale tree (`post_comment.sh` was on `origin/main` only). Agent guidance that says "check
whether it already exists" without specifying *against what* has a measurable false-negative
rate in a repository where several agents merge concurrently.

**A suspension with a precise lift-condition still never lifts.** `overseer.md:391` names a
specific issue whose closure would end the suspension. It closed five weeks ago. Prose is
not an evaluator, and the fix landing is what made the instruction wrong — the system was
more correct before #552 shipped than after. Caught only by finding #1211, filed hours
earlier by another agent, which had measured the gate as live; the first draft of this
finding asserted the gate was being bypassed and had to be corrected.

**Construction discipline held.** Comment posting moved to `bootstrap/post_comment.sh`
partway through and ran clean thereafter. The earlier hand-rolled `source …; gh …` pattern
prompted on every call and was hard-denied once — consistent with the prior session's
finding that construction beats configuration at the permission boundary.

---

## Artifacts produced

| # | Milestone | What |
|---|---|---|
| #1213 | v0.6.0 | `gh_query.py` CLI over `lib/github.py`; corrected twice as premises decayed |
| #1214 | v0.6.0 | CLAUDE.md: required existence check; generated script index |
| #1216 | v0.7.0 | Run in CI what can run in CI; extend the `HOS_ACTIONABLE_PRS` pre-filter |
| #1217 | v0.6.0 | Overseer stale stamp-disable + §60/cron-prompt contradiction |
| #1218 | v0.7.0 | Capped retry in the bash write wrappers |
| #1203 | v0.6.0 | Closed — partial-pull repair verified complete |
| #1202 | v0.6.0 | Design handoff reviewed; four decisions resolved |

**Findings:** `a-suspension-conditioned-on-external-state-never-lifts`,
`attestation-displaces-the-execution-it-attests-to`,
`state-assertions-decay-faster-than-their-documents`.

---

## Decisions resolved on #1202

1. **Fork:** cron-executed scripts live in the repo as source of truth, **copied into
   `<project>/bin/` at install**. Keeps them reviewed and versioned while the executed copy
   sits outside agent-writable space; changing what cron runs requires a human-run install.
2. **Cadence:** deferred until #1200 ships — the 8-commits-behind figure measured a broken
   sync, not an insufficient cadence.
3. **Lock-based skip as the default**, marker as backstop, so mid-session mutation cannot
   occur rather than being made survivable.
4. **`.claude/settings.json` generated per role** rather than tracked.

---

## Follow-ups owed

- `research/findings/README.md` is **41 findings behind** — pre-existing debt, not created
  here. Deliberately not half-fixed; needs its own pass.
- Copy-on-install (decision 1) introduces a drift risk: the installed copies can age against
  the repo source. Needs a currency check, in the shape of the existing generated-CODEOWNERS
  guard.
- A config update is owed to the human once #1202's design is fully settled.
