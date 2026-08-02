# Finding: Attestation Displaces the Execution It Attests To

**Role:** oversight-mechanism — a gate that verifies checks *were run* can occupy the slot where running them belongs, leaving no point in the pipeline that executes them

**First observed:** 2026-08-02, session `2026-08-02-ci-execution-and-branch-rule-verification.md`

---

## The Finding

When some checks genuinely cannot run in CI — subscription-authenticated CLIs, licensed
scanners, anything needing credentials CI must not hold — a reasonable design runs them
locally and has CI verify they were run. The attestation is honest about what it is.

The failure is that **the attestation slot then reads as the verification slot.** Because a
required check exists and is green, the pipeline looks covered. The question "does anything
here actually execute the tests?" stops being asked, and checks that had no auth constraint
at all — that could have run in CI trivially — are never migrated, because the gate they
would occupy appears filled.

The attestation is not wrong. It is *load-bearing beyond its design*.

### The instance

HOS runs gates, validators and tests locally and has CI verify a stamp. The rationale is
explicit in `.github/workflows/validation-check.yml` and correct: agy and codex use
subscription CLI auth that cannot be provisioned in CI.

Auditing what actually executes:

| Workflow | Required | Behaviour |
|---|---|---|
| `require-human-approval` | yes | approval gate |
| `require-overseer-approval` | yes | approval gate |
| `require-tier-ceiling` | yes | reads a committed validator artifact |
| `validation-check` | no | verifies a content-hash stamp |
| `shellcheck` | no | real static analysis, not gating |

Grepping every workflow for `pytest`, `unittest`, `run_gates`, `run_validators` returns
**nothing**, while `tests/automation/`, `tests/framework/` and `tests/oversight/` hold
substantial suites — the bootstrap wrapper tests alone are 568 lines.

`pytest` has no auth constraint. It was never excluded by the rationale; it was simply never
added, because the slot looked filled.

The chain has no executor:

1. The worker runs tests locally pre-PR.
2. The stamp attests to the tree's content.
3. CI verifies the stamp, and runs no tests.
4. The overseer is **forbidden** from re-running them — `.claude/agents/overseer.md:60`
   lists "Re-run inner-loop checks (validators, reviewer agents) that the worker should have
   run pre-PR" under "These are hard limits. No override path."

Between authoring and merge, nothing independently executes the suite.

### The corollary that misleads the audit

Asked whether branches should be required up-to-date before merge
(`strict_required_status_checks_policy`), the intuitive answer is yes — stale bases are a
known hazard, and this repository has a documented near-miss where a branch built on a
stale base proposed reverting 6,114 lines.

But re-running checks on a moved base only buys something **if the checks read the code.**
Two of the three required checks here are approval gates; the third reads a committed
artifact. Forcing re-verification would re-run all three and catch nothing, at the cost of
serialising a cron-driven PR queue.

The right question is not *"are checks re-run against the merged tree?"* but **"which
required checks analyse code at all?"** On this repository the answer was: none.

## Why this class is hard to detect

Every local signal is honest, so no single vantage point sees the gap:

- **The rationale is true.** agy/codex really cannot run in CI. A reviewer who checks
  whether the design is justified finds that it is.
- **The stamp is sound.** Content-hash based (#552), it correctly binds an attestation to a
  tree. Attacking the mechanism finds nothing wrong with it.
- **The tests exist and are good.** A coverage audit finds a healthy suite.
- **The required checks are green.** A branch-protection audit finds a protected branch
  with three required checks.

The gap lives between artefacts, in the assumption that a green required check implies
executed verification. Only enumerating each required check and asking *what does this one
actually do* surfaces it — the same producer/consumer reconciliation as
[`an-enabled-control-can-still-not-cover-its-target`](an-enabled-control-can-still-not-cover-its-target.md),
applied to execution rather than artifact type.

There is also a class attestation **cannot** cover regardless of quality: two branches can
each be validated locally and still break `main` when combined — a rename in one, a new
caller in another, merging cleanly in git. Neither author's local run ever saw the other's
code. Only post-merge or merge-queue execution catches it, and no attestation design can.

## Implication for research

Oversight-pipeline audits should classify every required check as **executing** or
**recording**, and treat a pipeline whose executing set is empty as unverified regardless of
how many checks are green. The count of required checks — the number most readily available
and most often cited — carries no information about this.

The economic argument is worth recording because it points the same way as the correctness
argument, which is unusual. In an agentic pipeline the reviewer is an LLM, so a PR with
failing tests consumes a full agent review cycle to discover what `pytest` reports in
seconds. Moving execution earlier is simultaneously the safer and the cheaper design; the
usual shift-left tradeoff does not apply, because the expensive stage is judgment, not
compute.

## What changed

- **#1216** (v0.7.0) — classify every gate/validator/suite CI-portable vs local-only with a
  recorded reason; run the portable set; make `pytest` a required check; narrow the stamp's
  scope to what genuinely cannot run in CI, so it stops implying coverage CI now provides.
- #1216 also extends `hos-cron`'s existing `HOS_ACTIONABLE_PRS` pre-filter to exclude PRs
  whose required checks are not green, so a failing PR consumes no overseer tokens.
- `strict_required_status_checks_policy` was **considered and rejected** for now — it would
  re-run two approval gates and an artifact read. The stale-artifact problem it appeared to
  address is #1170, and is not fixed by branch freshness.
