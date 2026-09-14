# Session: A Ruleset Regression Six Weeks Old, and Eight Rulings on Deterministic Agent Invocation

**Date:** 2026-09-14
**Role:** Scott, interactive session (ad hoc infra troubleshooting + governance spec review — not a designated HOS pipeline role), authenticated as himself, working from the Overseer clone
**Duration:** ~2 hours (approximate; not logged at session start, consistent with this repo's own finding that state claims should be checked rather than asserted from memory — this one wasn't checked)
**Artifacts:** `main-protection` ruleset updated (id `18044233`); classic branch protection deleted on `main`; 2 orphaned Actions runs cancelled; issue #1653 filed; comments posted on #1643 and #1644 recording eight human rulings on `docs/v0.7.0/REQUIREMENTS-1643-1644-deterministic-agent-invocation.md` §5

---

## What this session was

Two threads, discovered to be the same finding wearing two different costumes.

The first started as "clean up stale CI gates" and became a live-fire instance of
`a-decision-records-intent-not-enforcement.md`: a documented decision from six weeks ago had
already regressed, silently, because the tool that caused the original problem was never retired.

The second was a walkthrough of `REQUIREMENTS-1643-1644-deterministic-agent-invocation.md` — a
`pm-agent` requirements pass, dated the same day, that is the mechanism-level instance of #1360's
architecture direction ("deterministic code owns the workflow, the agent is called for
judgment"). Eight product/boundary decisions were escalated to the human; all eight were ruled on
in this session.

---

## Thread 1: the ruleset regressed to exactly its pre-fix state, and nobody had touched it

### What was found

`gh api repos/.../branches/main/protection` returned live data — 11 required status-check
contexts — when the documented, deliberately-chosen state (per `docs/MACHINE-ACCOUNTS-SETUP.md`
Step 6, decided 2026-06-23) was for classic branch protection to be **deleted**, with a
`main-protection` **ruleset** as the sole mechanism.

This is not a new finding. `research/sessions/2026-08-02-ci-execution-and-branch-rule-verification.md`
already verified, six weeks prior, that classic protection returned `404 Branch not protected` —
i.e., the correct, intended state was already live on 2026-08-02. Today it was not. Something
recreated it in between.

The something was identified: `scripts/framework/setup_branch_protection.sh` — a script that
predates the ruleset decision by a week (first added 2026-06-15) and was never retired despite
the setup guide's own explicit instruction ("Click Create, then delete the classic branch
protection rule at Settings → Branches"). It kept being actively extended with new required
checks through September, most recently the same day as this session, while the ruleset itself
sat frozen at its 2026-08-02 state — 3 required checks against the script's 11.

### Why this is the same finding, not a similar one

`a-decision-records-intent-not-enforcement.md` (filed from `2026-08-04-controls-that-never-fire`)
states the pattern precisely: *"A design decision, correctly reasoned and durably recorded, does
not propagate to code written afterwards... nobody disagrees with the decision, nobody argues
against it, and nobody applies it."* That session's own list of instances includes #1255 — *"a
promise retired with the thing that would have kept it"* — a documented cleanup step (retire sync
machinery, add an inline committer) where only the first half ever happened.

This is the same shape, with one addition worth naming as its own variant: **the decision here had
already been correctly applied once** (2026-08-02's session confirms it), and it regressed anyway,
because the thing that produced the original problem — a script whose job was never redefined
after the decision that should have obsoleted it — kept running on its own schedule, independent
of whether anyone was thinking about branch protection that week. `a-decision-records-intent-not-enforcement`
is about code written *after* a decision quietly violating it. This is a decision *executed once,
correctly*, decaying because the artifact that caused the original violation was left alive rather
than removed. A prior instance of exactly this general shape — a control whose target moved but
whose mechanism didn't retire with it — is `dismiss-stale-reviews-cascade-in-batch-merges.md` and
the related `an-enabled-control-can-still-not-cover-its-target.md`, both from the same 2026-08-02
session.

### The fix applied, and its honest limitation

Live state was corrected today: the ruleset now carries the full 11-context list, classic branch
protection is deleted, and the ruleset's bypass list holds exactly one actor — the human, mode
`always` — confirmed in this session as intentional (see Thread 2 preamble on trust boundaries,
below). Issue #1653 was filed asking for `setup_branch_protection.sh` to be rewritten against the
Rulesets API so it can no longer recreate the redundant mechanism.

**The honest limitation, stated in the same terms `2026-08-04`'s session used for its own remedy:**
*"Validate at the write path, not in the instructions."* Today's fix is the same *kind* of act as
the one that failed six weeks ago — a human (or an agent) doing the deletion by hand, once, with a
follow-up instruction (now #1653, then a paragraph in a setup guide) asking someone to make it not
regress. Nothing yet prevents a third occurrence beyond a filed issue and a comment in a script.
#1653's body does propose a mechanical guard (a preflight check that fails if classic protection
still exists on the target branch) — whether that lands, or whether this reverts a third time, is
the actual test of whether this session's fix was different in kind from 2026-08-02's, or just a
repeat with better documentation.

---

## Thread 2: eight rulings on `REQUIREMENTS-1643-1644-deterministic-agent-invocation.md`

### What the document found, independently re-derived from the repo

The document (`pm-agent`, dated 2026-09-14, DRAFT for architect) is the requirements pass for
#1643/#1644, and directly operationalizes #1360's architecture direction, which itself names
`2026-08-04-controls-that-never-fire` as its own measurement basis. Its verification findings
sharpen that session's pattern #1 (the security-relevant parameter nobody ever passes) into
something structurally worse:

- **`decide_merge_authority()` has no reviewer, sign-off, or dimension parameter of any kind** —
  its only review-shaped input is a caller-supplied `oversight_verdict` string, checked once for
  `!= "PROCEED"`, with nothing verifying where the string came from.
- **The overseer's own agent definition never dispatches any of the eight review-dimension
  agents** — `dispatches:` names exactly two (`oversight-evaluator`, `risk-assessor`); the
  overseer's knowledge of code-review, security-review, etc. is entirely mediated by artifacts the
  worker wrote about itself.
- **The one mechanism built on durable, committed, cross-clone-visible evidence
  (`signoff_gate.py`) is used only by the worker's own self-assessment gate** — the party it
  exists to check, not the party that's supposed to check it.

That last one is close to a standalone finding in its own right — it's the same shape as
`self-classification-cannot-gate-the-human-boundary.md` (a governed party's self-report cannot be
the control that gates it) but sharper: here the *durable* evidence mechanism exists and is
correctly built, and the only bug is that it is wired to the wrong party. Flagged here as a
candidate for its own `research/findings/` entry rather than written as one now, since this
session didn't extract it in isolation — worth a follow-up pass.

### The rulings

Recorded verbatim on #1643 (binding on both #1643 and #1644, per the document's own citation
convention); a pointer comment was posted on #1644 since it currently has zero native comments.

| # | Ruling | One-line reasoning |
|---|---|---|
| Q1 | Hard block, fail-closed on invocation failure | Skipping a check is how bad code reaches the repo |
| Q2 | Overseer always independently reruns every AI judgment dimension; never trusts worker-produced results; no risk-tier subsetting | A prior attempt to pass worker results to the overseer caused more stalls than it saved — reverting to full independent rerun, accepting the duplicate cost |
| Q3 | `bypassPermissions` is a stopgap for not-yet-converted legacy surfaces only; new invocation surfaces are scripts with scoped permissions by default | Sandbox rollout (#1542) will mostly obsolete the question soon; until then, don't grow the blanket-bypass surface |
| Q4+Q6 | No in-script convergence loop. Each round/stage is a separate cron-driven top-level invocation, generalizing #1354's stage-per-cycle pattern to the full build pipeline | Eliminates the nested-invocation budget risk (VF-11: up to 9 nested sessions in one 1800s cycle) by construction — there is no nesting |
| Q5 | Mechanical fingerprint-recurrence wins as the fast, code-owned stuck detector (per PM's original recommendation); but a round may not declare itself *converged* on its own say-so — that confirmation routes through the existing cross-vendor second-review mechanism | Same-vendor self-grading is the thing #1216 already ruled out for review generally; applied here to loop-exit specifically, per the human's "AI doesn't excel at parallel work — use another AI to check work" |
| Q7 | Primitive → #1643 → #1644, confirmed. #1644 flagged for its own follow-up requirements/technical-design pass rather than proceeding against this document's Track 3 as drafted | Q4/Q6 changed #1644's build-side mechanism materially (cron-driven decomposition replaces the in-script nested loop the current Track 3 work items assume) |
| Q8 | PM's original text stands: bounded looping is acceptable in principle, architect operationalizes the specific boundary | No numeric ruling beyond REQ-C2's existing recommended default (cap 3) |

### The gap the human caught that the document's Q4/Q6 recommendation didn't cover

Ruling on Q4+Q6 together surfaced a real hole in the proposal as drafted: nothing in "planner
decomposes work into linked issues, terminates, next cron cycle picks up the next stage" actually
guarantees the *next* cycle picks up the *expected* task rather than something else off the queue,
or that an agent landing on the wrong stage's issue (a coder invocation hitting a spec-only issue)
does anything other than silently misfire. This needs an explicit stage-type tag/label mechanism —
flagged in the ruling as unresolved, with an explicit pointer to design it alongside the pending
`needs-ai` → `needs-worker`/`needs-overseer` rename (#1349), since it's the same class of problem
("which actor/stage is this issue for") and building a second, parallel labeling scheme for it
would be its own instance of the duplication class this whole document exists to prevent.

---

## The through-line between both threads

Both are the same underlying claim, at different layers: **a mechanism that once matched a
decision does not stay matched to it for free**, whether the mechanism is a GitHub API resource
(the ruleset) or a merge-authority function's parameter list (`decide_merge_authority()`). Neither
failure was caught by anything that runs automatically — both surfaced because someone asked "is
this actually still true?" rather than trusting that a decision, once made and once correctly
implemented, stays implemented. That is the same operating principle `2026-08-02`'s session named
as its central learning: *"Every correction this session came from running a command; none from
reading configuration or documentation."* Today's corrections came from the same place.

---

## Related

- `research/sessions/2026-08-02-ci-execution-and-branch-rule-verification.md` — verified the
  correct ruleset-only state that regressed by this session
- `research/sessions/2026-08-04-controls-that-never-fire.md` — the pattern this session's Thread 2
  findings extend, and the measurement basis #1360 itself cites
- `research/findings/a-decision-records-intent-not-enforcement.md` — Thread 1 is a recurrence of
  this finding, with the added variant that the decision had already been correctly applied once
- `research/findings/an-enabled-control-can-still-not-cover-its-target.md` — same 2026-08-02
  session, same ruleset, a different coverage gap
- `research/findings/self-classification-cannot-gate-the-human-boundary.md` — the shape VF-4/VF-5/VF-6
  sharpen; a durable-evidence mechanism wired to the wrong party is a candidate variant, not yet
  written up separately
- Issues: #1360 (architecture direction), #1643, #1644 (this session's rulings), #1653 (filed this
  session, the mechanical fix for Thread 1), #1349 (label rename, cross-referenced in the Q4/Q6 gap),
  #1354 (stage-per-cycle precedent generalized by Q4/Q6)
