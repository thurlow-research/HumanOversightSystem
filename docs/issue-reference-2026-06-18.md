# Issue Reference — 2026-06-18

This document is a local reference for oversight to verify that GitHub issues
exist with the expected content. Generated because GitHub UI was returning 404
on some issues and rate limits made API verification unreliable.

Sections: [v0.4.0 Active](#v040-active) · [v0.4.0 Needs-Human](#v040-needs-human) · [v0.5.0 Research](#v050-slr) · [Unfiled](#unfiled)

---

## v0.4.0 Active {#v040-active}

### #407 — Worker loop meta-issue (milestone control)
**Labels:** `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker  
**State:** open (close when all v0.4.0 work complete and release cut)

Worker phase 1-4 loop guidance. Instructs the worker to:
1. Fix known v0.4.0 issues (one PR at a time, stop after each)
2. Run full test suite, file issues for failures
3. Run release validation suite
4. Run outer loop (second review + panel)

Worker must not close this issue — ScottThurlow closes it when the release is cut.

---

### #411 — Bug: worker missed CHANGES_REQUESTED reviews for multiple loops
**Labels:** `bug`, `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker

Worker's Step 0 only checked `mergeable:CONFLICTING`. It did not read review
bodies or comments. Two rounds of CHANGES_REQUESTED from HOSOversightTutelare
were missed for several hours before the human noticed.

Fix: worker.md Step 0 must read all reviews AND all comments on every open PR,
not just check merge-conflict status.

---

### #414 — Bug: worker loop protocol missing review-body read step
**Labels:** `bug`, `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker

Related to #411. Filed separately to track the protocol gap vs. the symptom.
The worker.md agent spec must explicitly document the required order:
1. `gh pr list` (open PRs)
2. For each: `gh pr view --json reviews,comments` (all review bodies + comments)
3. Address any CHANGES_REQUESTED before picking new work

---

### #422 — Design: validation stamp conflict cascade; gitignore is temp fix
**Labels:** `bug`, `enhancement`  
**Milestone:** v0.4.0 — Autonomous Worker

Every PR merge updated main's `all-phases.stamp`, immediately conflicting all
other open PRs. During v0.4.0 this required 15+ rounds of manual conflict
resolution.

Temporary fix applied: `scripts/framework/validation-stamps/` added to
`.gitignore`. CI check now skips when stamp is untracked.

**Must back out temp fix when redesigned.** Redesign options:
- Per-branch stamps with merge-base comparison
- Content-addressed stamps (hash of validated files, not timestamp)
- CI-only validation (skip local stamp requirement entirely)

---

### #444 — Full test suite run required before release cut
**Labels:** `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker

`./scripts/framework/run_tests.sh` (full suite + 80% coverage gate) must pass
clean before the release is cut. File separate issues for each failure.
This is Phase 2 of the #407 loop.

---

### #450 — Policy: PR size limits (≤15 files, ≤10 commits, 25-file hard ceiling)
**Labels:** `enhancement`, `documentation`  
**Milestone:** v0.4.0 — Autonomous Worker

Empirical finding from v0.4.0 PR cascade: large PRs cause merge conflicts,
make reviewer work harder, and increase the blast radius of mistakes.

Policy:
- Recommended: ≤15 files, ≤10 commits
- Hard ceiling: 25 files (worker must split before submitting)
- Document at `docs/PR-SIZE-POLICY.md`
- Wire into worker.md and overseer.md as explicit checks

---

### #454 — Bug (HIGH): overseer reads only CI status, not validator artifacts
**Labels:** `bug`, `security`  
**Milestone:** v0.4.0 — Autonomous Worker  
**Severity:** HIGH

Overseer approved ~40 PRs without reading `.claudetmp/oversight/validators/`
artifacts or the sign-off register. It relied only on CI status checks.

This means the sign-off register, risk tier, and reviewer findings were
never actually verified by the overseer — it just trusted that CI ran.

Fix: overseer CORE must read and verify:
- `.claudetmp/oversight/validators/summary.json` (risk tier)
- Sign-off register (all required fields present)
- At least spot-check reviewer finding resolution

**Blocked on #511** (product-boundary checkpoint — see Needs-Human section).

---

### #455 — Bug: worker skipped pm-agent/architect/tech-design for multiple v0.4.0 changes
**Labels:** `bug`, `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker

Multiple v0.4.0 changes went directly to coder without running the required
pipeline (pm-agent triage → architect triage → technical-design triage → coder).
Root cause: honor-system enforcement — the worker chose whether to run the
pipeline, and often skipped it for "small" changes.

Fix: triage agents (#468) gate the pipeline entry mechanically. The worker
cannot bypass by deciding a change is "small enough."

---

### #456 — Pre-release review gate (runs last in v0.4.0 sequence)
**Labels:** `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker

Final quality gate before cutting the release. Runs after Phase 3
(release validation suite passes). Requires:
- All open v0.4.0 issues closed or deferred to v0.5.0
- `docs/releases/v0.4.0.md` complete
- Panel sign-off (run_panel.sh clean)
- ScottThurlow human authorization to cut

Worker closes this issue only when ScottThurlow authorizes release cut in
this issue thread.

---

### #468 — Triage agents: pr-triage, arch-triage, tech-design-triage (Haiku 4.5)
**Labels:** `enhancement`, `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker

Lightweight Haiku 4.5 gateway agents that mechanically enforce pipeline
discipline. Each agent answers a binary question before the next stage:

- **pr-triage**: does this change require pm-agent review?
- **arch-triage**: does this change require architect review?
- **tech-design-triage**: does this change require technical-design update?

Worker is required to call each triage agent before proceeding to the next
pipeline stage. Agent says NO → skip that stage. Agent says YES → must run
that stage before coder.

Prevents the #455 pattern of workers self-certifying that a stage can be skipped.

---

### #472 — Bug: two divergent codeowners.py implementations
**Labels:** `bug`, `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker

Two files with different glob semantics both feeding authorization gates:
- `scripts/oversight/codeowners.py` — overseer's CODEOWNERS gate (SPEC-303b)
- `scripts/automation/lib/codeowners.py` — worker automation library

These diverged during v0.4.0. One may have different matching behavior for
edge cases. Fix: consolidate to a single canonical implementation, update all
callers. Architect must decide which is canonical.

---

### #481 — Fix: classify_framing() missing from triage.py (SPEC-381)
**Labels:** `bug`, `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker  
**PR:** open (#481 or adjacent)

`feat/v040-worker-254-lib` merged a version of `triage.py` that only had
`triage()`. The version with `classify_framing()` and `FramingVerdict` (SPEC-381
adversarial framing guard) was overwritten.

Fix: restore `classify_framing()` (183 lines) and its 71 tests. Both
`triage()` (issue classification) and `classify_framing()` (framing guard)
must coexist in `scripts/automation/lib/triage.py`.

---

### #482 — Fix: validation stamp bypass must be time-boxed
**Labels:** `bug`, `needs-ai`  
**Milestone:** v0.4.0 — Autonomous Worker  
**PR:** open

The gitignore bypass for stamps (#422 temp fix) has no expiry. If never
removed, CI permanently skips validation currency checks.

Fix: add `STAMP_BYPASS_DISABLED_UNTIL="2026-12-31"` constant to
`check_validation_current.sh`. After that date, the script exits 1 with
FAIL rather than SKIP, forcing the team to complete #422 redesign.

---

## v0.4.0 Needs-Human {#v040-needs-human}

### #511 — needs-human: #454 fix requires product-boundary clearance
**Labels:** `needs-human`  
**Milestone:** v0.4.0 — Autonomous Worker  
**Assigned to:** ScottThurlow  
**State:** open

**Action required:** ScottThurlow must authorize or decline the #454 fix.

Background: fixing #454 (overseer reads validator artifacts, not just CI status)
changes the overseer's merge throughput. Currently the overseer approves PRs
quickly by trusting CI. After the fix, it must read and interpret artifact files
on every PR — slower, but correct.

**Product-boundary question:** Is reduced autonomous merge throughput acceptable
in exchange for the overseer actually verifying what it claims to verify?

**Options:**
- **A (recommended):** Authorize the fix. Accept that overseer throughput
  decreases. The current behavior is a compliance gap — overseer approval is
  semantically hollow if it doesn't verify artifacts.
- **B:** Defer to v0.5.0. Accept the compliance gap for the remainder of v0.4.0
  and redesign the overseer's verification model more carefully.

**Protocol:** When you decide, comment here, remove `needs-human`, add `needs-ai`
if Option A, close if Option B. Then assign back to HOSWorkerTutelare.

---

## v0.5.0 SLR-Derived Issues {#v050-slr}

*All tagged `slr-finding`. Sources: Cobb & Mills (1990), Poppendieck & Cusumano (2012).*
*Full synthesis: `research/findings/cleanroom-sqc-and-lean-applied-to-hos-consumer-projects.md`*

---

### #514 — MTTF/B-factor reliability certification as consumer PR gate
**Labels:** `enhancement`, `slr-finding`  
**Milestone:** v0.5.0 — Quality  
**Bucket:** 3 (Governance)

Add MTTF (Mean Time To Failure) certification tracking to the HOS consumer
pipeline. B = MTTF_{n+1} / MTTF_n; if B < 1, quality is regressing.

Consumer-facing: step-manifest.yaml gains optional fields:
```yaml
mttf_target: 500  # hours, minimum acceptable
mttf_gate: true   # overseer bounces if predicted MTTF regresses
```

Overseer tracks observed failures during certification testing, estimates MTTF
using the exponential model, bounces PR if B < 1 or predicted MTTF < target.

Scope: new step-manifest fields, MTTF estimation (Python), overseer gate check,
consumer documentation.

---

### #515 — Usage-profile-weighted test requirements in step-manifest
**Labels:** `enhancement`, `slr-finding`  
**Milestone:** v0.5.0 — Quality  
**Bucket:** 3 (Governance)

Cleanroom: tests drawn from actual usage distribution are 21x more cost-effective
than coverage-based tests (Adams study). step-manifest.yaml gains a
`usage_profile:` field pointing to a frequency-weighted endpoint map.

```yaml
steps:
  - id: reservations
    usage_profile: docs/usage-profile-reservations.yaml
    usage_weighted_coverage_target: 0.95
```

unit-test and system-test CORE prompts: weight test design toward high-frequency
paths. Scope: step-manifest fields, usage_profile.yaml schema, agent CORE updates,
consumer documentation.

---

### #516 — Lean waste report from audit log at each release
**Labels:** `enhancement`, `slr-finding`  
**Milestone:** v0.5.0 — Quality  
**Bucket:** 4a (Observability)

Generate a lean waste report from `audit/oversight-log.jsonl` at each release.
Classifies cycle time into lean waste categories:

| Waste | HOS signal |
|---|---|
| Defects (rework) | pr-bounced events |
| Waiting | Time between pr-opened and pr-merged |
| Overproduction | Validators run on irrelevant file types |
| Transport | Bounce-fix-resubmit cycles |

Produces a one-page Markdown report at release. Feeds 'keep getting better'
lean principle with data. Integrated into cut_release.sh.

---

### #517 — Quality ratchet: overseer enforces monotonically improving defect density
**Labels:** `enhancement`, `slr-finding`  
**Milestone:** v0.5.0 — Quality  
**Bucket:** 3 (Governance)

Track defect density (findings per KLOC) across releases. If new release has
higher defect density, overseer downgrades merge ceiling and flags regression.

Configurable in step-manifest.yaml:
```yaml
quality_ratchet:
  enabled: true
  metric: findings_per_kloc
  action: warn  # or: block_release
```

Integration: release-time comparison of defect metrics, cut_release.sh,
overseer CORE awareness of quality trend.

---

### #518 — Configurable WIP limits for consumer pipeline (Lean Kanban)
**Labels:** `enhancement`, `slr-finding`  
**Milestone:** v0.6.0  
**Bucket:** 3 (Governance) — deferred, needs design

Installable WIP constraint for consumer projects running multiple workers:
```yaml
# .hos/coordination.yaml
max_prs_in_flight: 2
max_step_wip: 1
kanban_alert_threshold: 3  # days
```

Deferred: requires design on how WIP limits interact with overseer batch
merge serialization, and whether limits are per-cid, per-step, or global.

---

### #519 — Enforce separation of development and certification testing
**Labels:** `enhancement`, `slr-finding`  
**Milestone:** v0.5.0 — Quality  
**Bucket:** 3 (Governance)

Cleanroom core safety: certification testing is done by a team independent of
development. Currently HOS requires tests pass but doesn't enforce who ran them.

Changes:
- Overseer verifies `docs/system-test-plan.md` was authored by system-test agent
- system-test CORE prompt strengthened: "derive tests from spec/design, not from
  the unit-test plan"
- For projects using #515 (usage-profile), certification draws from usage profile,
  not the coder's coverage map

Presupposes #515. Adjacent to #454 (overseer reads artifacts).

---

### #520 — B-factor monotonic improvement as overseer merge gate (hard gate)
**Labels:** `enhancement`, `slr-finding`  
**Milestone:** v0.6.0  
**Bucket:** 3 (Governance) — deferred, needs architect ruling

Stronger version of #517: B-factor becomes a hard overseer merge gate, not
just a release-time warning. If B < 1, overseer refuses to merge.

Design questions (why deferred):
- How many increments before the MTTF estimate is stable enough to gate on?
  (Safe default: disabled until N ≥ 3 increments)
- Per-step MTTF curves or global?
- Does overseer compute inline, or read a certification-team artifact (#519)?

Requires #514 (MTTF infrastructure) and #519 (independent certification data).
Requires architect ruling — changes overseer merge criteria, which is a governance
decision.

---

## Unfiled (to be filed when rate limit clears) {#unfiled}

### [UNFILED] GitHub API robustness: local read cache + write queue for worker
**Target labels:** `enhancement`  
**Target milestone:** v0.5.0 — Quality  
**Target bucket:** 2 (Performance/Cost)

Worker currently fetches live from GitHub on every loop iteration with no local
cache and no write queue. Rate limits cause hard failures with no retry.

**Local read cache:**
- JSON/SQLite at `.claudetmp/github-cache/` keyed by resource
- ETags for conditional GET (GitHub returns 304 Not Modified; doesn't count
  against rate limits)
- Worker reads from cache if fresh, conditional fetch otherwise
- Write operations invalidate affected entries immediately

**Write queue:**
- Append-only JSONL at `.claudetmp/github-queue.jsonl`
- Each entry: `{op, resource, payload, idempotency_key, enqueued_at}`
- On rate limit / transient error: enqueue instead of failing
- Next loop iteration flushes queue before doing new work
- Idempotency keys prevent duplicate mutations on replay

**Design questions requiring architect ruling before implementation:**
1. Cache staleness policy — how stale can active-PR review state be?
   (Safe default: always-fresh for the active PR; cached-only for inactive issues)
2. Queue ordering — strict ordering or idempotent best-effort?
   (Labels: idempotent fine; comment sequences: ordering matters)
3. Implementation location — `scripts/automation/lib/github_client.py`
   or a wrapper around gh CLI calls in worker.md?
