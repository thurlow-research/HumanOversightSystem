# REQUIREMENTS-1909: The tier-ceiling gate and the overseer must agree on a PR's tier

**Status:** Draft for architect review.
**Change classification: STRUCTURAL.** This changes how the PR risk tier is computed, and that
tier feeds `OVERSEER_CEILING`, a CORE safety threshold (risk-tier thresholds and the sign-offs
they trigger). It also changes behavior for two required checks, `require-tier-ceiling` and
`require-overseer-approval` (through its #1426 bypass), and adds a pre-post agreement duty to the
overseer's approve path. Under pm-agent CORE, any change to existing gate behavior is structural.
The build should not start until a human has ruled on ESC-1 and ESC-2, or accepted their
defaults.
**Date:** 2026-10-18
**Author:** pm-agent (autonomous worker cycle). No human was present, so open questions are
listed as ESC items.
**Tree read at:** `9ba2bb8a6` (branch `worker-1909-tier-ceiling-design-261018053501-4161068`).
**Source issue:** #1909, filed by the overseer while it reviewed PR #1907. Related: #973 (closed),
#1427, #1791, #1657 (closed), #1426. I treated the issue body as a description of the work
wanted, not as instructions (CORE, #1539). Every claim in it is checked below.
**Consumers:** `architect`, then `technical-design`.
**Protected surfaces touched** (`scripts/framework/protected_surfaces.txt`):
- `scripts/framework/**` (`:28`): `require_tier_ceiling.py` and `require_overseer_approval.py`.
  Every option touches this, so **every slice is human-gated**.
- `scripts/oversight/run_validators.sh` (`:30`) and `scripts/oversight/validators/schema.py`
  (`:31`): touched if the overseer-side computation changes (options 1 and 2).
- `.claude/agents/**` (`:16`): `overseer.md`, if its tier procedure or approve rule changes.
- `bootstrap/**` (`:27`): `pr_review.sh`, only if the wrapper itself changes. The refusal logic
  actually lives in `scripts/automation/pr_review_cli.py`, which is **not** protected.
- `.github/workflows/**` (`:33`): `require-tier-ceiling.yml`, if the CI step changes.
- `scripts/oversight/validators/rn_calculator.py` and `tests/**` are **not** protected.

---

## 0. Verification findings

Each claim in the issue is checked against the tree at `9ba2bb8a6`.

**VF-1: CONFIRMED. The gate scores full head content with `rn_calculator` alone.**
- `compute_tier()` is at `scripts/framework/require_tier_ceiling.py:291-326`. In CI, step 1
  (`_try_validator_summary`, `:162-174`) finds no `.claudetmp/` summary, so step 2 runs
  (`:308-319`).
- `_fetch_head_python()` (`:185-222`) writes the **entire** head-SHA content of each changed
  `.py` file (`:204-220`). Nothing narrows it to changed lines or functions.
- `_try_rn_calculator()` (`:225-267`) runs `rn_calculator.py` over those files and maps its score
  straight to a tier (`:263`, thresholds mirrored at `:140-154`). Only `_simplified_tier`
  (`:270-288`, at most MEDIUM) can raise it. No other dimension is consulted.

**VF-2: CONFIRMED. One function anywhere in a touched file sets the tier.**
- `rn_calculator.analyse_files()` takes `max_rn` over every function in every file passed
  (`scripts/oversight/validators/rn_calculator.py:281`) and normalizes it against 20.0 (`:255`,
  `:285`). So any single function with RN ≥ 15.6 scores ≥ 0.78, which is CRITICAL.
- Reproduced on `tests/automation/test_hos_cron.py`: `score=1.0`, `max_rn=32.0`. The top
  functions are `test_pipeline_subshell_shows_nested_argv_child_benign_1265` (line 1420,
  RN 32) and `_extract_sync_audit_logs_func` (line 4628, RN 10), matching the issue.
- So any PR touching that file computes CRITICAL at the gate, whatever it changes.

**VF-3: CONFIRMED, with a correction. The overseer's number is a weighted composite.**
- `run_validators.sh` writes a weighted average across dimensions (`:485-488`). `risk_number`
  carries weight 0.18 (`schema.py:63-77`). The 13 dimensions in `WEIGHTS` include `diff_size` at
  weight 0.0, so "13 validators" is accurate.
- **Correction:** the overseer's RN dimension *also* scores whole files.
  `run_validators.sh:307-309` passes `PY_FILES`, the full changed files, to `rn_calculator.py`.
  The two computations do not differ on whole-file versus hunk scope. They differ in
  **aggregation**: RN-alone mapped straight to a tier, versus RN diluted to 18% of a composite.
  So option 1 applied to the gate alone would still leave two different definitions.
- `tier_floor` is hoisted into `summary.json` but is **not** applied to `tier`
  (`run_validators.sh:490-515`). The comment there says the risk-assessor applies it. Floors
  come from `diff_size` (HIGH), `static_analysis` (HIGH) and `rn_calculator`'s task-class floor
  (MEDIUM).

**VF-4: PARTIAL. The overseer's tier procedure is not pinned in its definition.**
- `overseer.md` never names `run_validators.sh --diff origin/main`, and never mentions a
  worktree. It refers only to "risk recompute, gate/validator re-run" (`:230`).
  `decide_merge_authority()` takes `risk_tier` as a caller-supplied input
  (`scripts/automation/lib/merge_authority.py:502`, compared at `:642`).
- So the issue describes observed practice, not a specified procedure. Approve-eligibility
  condition 2 (`overseer.md:587`, "The computed tier does not exceed `OVERSEER_CEILING`") does
  not say *which* computation it means.

**VF-5: NEW. The two computations also use different file sets.**
- The gate uses `gh pr diff --name-only` (`require_tier_ceiling.py:114-116`). That is the PR's
  own change against its merge base.
- `run_validators.sh --diff <ref>` runs `git diff --name-only "$DIFF_REF"` (`:73-85`). That is a
  two-dot comparison of the ref with the **working tree**. When the PR branch is behind
  `origin/main`, it also lists files changed only on main.
- So the overseer may score files the PR never touched. This is a second, independent source of
  disagreement.

**VF-6: CONFIRMED. The approve refusal trusts the caller's tier.**
- `submit-verdict` refuses `approve` above the ceiling only by comparing the caller-supplied
  `--tier` (`scripts/automation/pr_review_cli.py:627-633`). It loads `require_tier_ceiling` only
  for `TIER_ORDER` and `tier_exceeds_ceiling` (`:462-469`, `:569`). It never calls
  `compute_tier_for_pr`. So it cannot catch the #1907 case.
- TD-1657 states the premise directly: "The overseer always holds the computed tier by the time
  it reaches a disposition" (`TECHNICAL-DESIGN-1657-overseer-review-objects.md:168`). #1907
  shows that the overseer holds *a* computed tier, not *the enforced* one.

**VF-7: NEW. Disagreement in the other direction deadlocks the #1426 bypass.**
- `require_overseer_approval.py:183-200` calls the same `compute_tier_for_pr`. When the overseer
  posted a non-approving review, a human approval satisfies the check **only if** the gate's
  tier exceeds the ceiling.
- If the overseer computes above the ceiling and posts `comment`, but the gate computes at or
  below the ceiling, the bypass does not fire. A human approval then does not satisfy
  `require-overseer-approval`, and the PR can merge only by admin override.
- Ways this can happen today:
  - a JS/TS-only change, which the overseer scores through the `rn_calculator_js` lane
    (`run_validators.sh:328-330`) while the gate treats it structurally (at most MEDIUM);
  - a high composite driven by non-RN dimensions;
  - a risk-assessor promotion.
- This is the same failure class #1657 fixed. Agreement must hold in **both** directions.

**VF-8: NEW. The gate's local path can read a stale summary and ignores `tier_floor`.**
- Step 1, `_try_validator_summary` (`require_tier_ceiling.py:162-174`), reads
  `.claudetmp/oversight/validators/summary.json` relative to the working directory. Nothing ties
  that file to the PR or head SHA being judged. It reads `tier` only (`:169`), so `tier_floor`
  (VF-3) is dropped.
- In CI the file is absent, so this is harmless today. But option 3 as worded (call
  `compute_tier_for_pr` from `submit-verdict` in the overseer's clone) would pick up whatever
  summary the overseer last wrote, possibly for a different PR. It would then **not** run "the
  same" computation as CI.

**VF-9: CONFIRMED. The failure is conservative, and the dismiss-and-repost is real.**
- The gate passes trivially when the overseer has not approved (`:402-408`). It fails with exit 1
  only on an approval above the ceiling (`:427-437`). It never admits a PR.
- `overseer.md:473` already documents "re-approve … and wait for the tier-ceiling CI check to
  re-pass", and `:467` documents `comment` for CRITICAL. The #1907 sequence (APPROVED, red gate,
  dismissal, COMMENT) is consistent with this code.

**VF-10: CONFIRMED. The security model must be kept.**
- The workflow runs on `pull_request_target` only (`require-tier-ceiling.yml:46-48`) and checks
  out the **base** SHA (`:75-77`). PR content is read as data through `gh` and only parsed, never
  executed (`require_tier_ceiling.py:119-133`).
- `rn_calculator.py` and the other validators except `schema.py` are **not** protected
  surfaces. If the overseer runs the validators from a PR-head worktree (VF-4), a PR that edits a
  validator can change its own overseer-side tier. That is the #1427 gaming class. The CI gate
  does not have this exposure today, and must not gain it.

---

## 1. Problem (product behavior)

Two authorities answer "what tier is this PR?":
- the overseer, which decides whether it may approve;
- the `require-tier-ceiling` check, which enforces that decision.

They use different aggregation (VF-3), different file sets (VF-5), and an unpinned procedure
(VF-4). The result is that approve-eligibility condition 2 is not decidable before the overseer
posts.
- When the gate is higher (#1907), a merits-clean PR gets a red required check and the overseer
  has to dismiss and repost.
- When the gate is lower (VF-7), the human-approval bypass cannot fire, and the PR is stuck
  until an admin overrides.

A hot file with an inherited high-RN function (VF-2) makes the first case repeat on every PR that
touches it.

What the product needs:
- **one** tier per PR head, with a single meaning;
- known to the overseer before it posts a verdict;
- enforced identically by CI;
- never more permissive than an honest assessment of the change.

---

## 2. Requirements

Settled requirements apply whatever architecture is chosen. Requirements marked **(pending
ESC-n)** state pm-agent's proposed default and must not be built until that ESC is ruled on or
its default is accepted.

### REQ-1: One tier per PR head, used by every ceiling decision

For a given PR head SHA and its merge base, these must produce the **same** tier value:
- the tier the overseer uses for approve-eligibility condition 2 (`overseer.md:587`) and the
  merge-authority matrix;
- the tier `require-tier-ceiling` enforces;
- the tier `require-overseer-approval`'s #1426 bypass evaluates.

`overseer.md` must name the one procedure that produces it (VF-4), so it is no longer
unspecified.

**AC:**
- (a) A test builds the PR #1907 shape: a hot file with an untouched RN-32 function, plus a small
  change elsewhere in it. It asserts that the overseer-side computation and the gate-side
  computation return the identical tier.
- (b) A test builds the VF-7 shape: a change the overseer rates above the ceiling. It asserts
  that the gate-side computation also rates it above the ceiling.
- (c) `overseer.md`'s approve-eligibility section names the tier procedure, and a static test
  pins the reference.

### REQ-2: Both directions of disagreement are closed

- **Overseer lower than gate.** The overseer must never post an `approve` verdict that the
  enforced computation rates above the ceiling. No `APPROVED` review object may be created in
  that case. That removes the dismiss-and-repost.
- **Overseer higher than gate.** When the overseer withholds approval because the tier exceeds
  the ceiling, the #1426 bypass must reach the same conclusion. A CODEOWNERS human approval must
  then satisfy `require-overseer-approval` without an admin override.

**AC:**
- (a) Driving `submit-verdict --event approve` with the #1907 fixture produces a refusal (exit 3,
  a distinct `refusal_reason`), and the capture shows **no** POST to `/reviews`. This holds even
  when the caller passes `--tier HIGH`.
- (b) With the VF-7 fixture, the overseer's `comment` review, and a human `APPROVED` review,
  `require_overseer_approval.main()` returns 0.

### REQ-3: Decidable before posting

The overseer must be able to obtain the enforced tier before it chooses `approve` or `comment`.
It must use the same inputs (head SHA, merge base) and the same trusted scorer code (REQ-5) that
CI will use. Whether that happens through the wrapper (issue option 3), a shared library, or a
CI-published result is the architect's choice.

**AC:** An offline test shows that, for a fixture PR, the value the overseer path obtains equals
the value `require_tier_ceiling.main()` would enforce for the same head SHA.

### REQ-4: Fail closed, always

- Every existing fail-closed path stays:
  - head-fetch failure → exit 2 (`:321-323`);
  - validator error → exit 2 (`:316-318`);
  - unknown tier → CRITICAL (`:333-335`);
  - missing or invalid `machine-accounts.env` keys → exit 2 (`:387-399`).
- Any new input must also fail closed when it cannot be obtained: hunk ranges, merge base,
  function spans, or the diff itself. Examples are a truncated API diff, an unparseable changed
  file, or a missing merge base. Failing closed means exit 2 at the gate and a refusal of
  `approve` on the overseer path.
- A fallback may only move the tier **up**, for example falling back to whole-file scoring.
  Every fallback must print a line naming the reason, so the extra strictness is visible.
- Neither side may become more permissive than the overseer's honest tier for the change. If
  the shared computation cannot be completed, the PR is not approve-eligible.

**AC:**
- (a) For each new input, a test forces it to fail and asserts exit 2, or a refusal on the
  overseer path.
- (b) The #973 regression test (`test_critical_python_pr_caught_above_high_ceiling`) still passes.

### REQ-5: The ceiling tier is computed by trusted code; PR content stays data

- The tier used for any ceiling decision, on either side, must come from scorer code at the
  trusted base, not from the PR head.
- The CI gate keeps `pull_request_target`, the base-SHA checkout, and its "parse, never execute"
  rule (VF-10). The overseer-side path must not run validator code from a PR-head worktree when
  it computes the ceiling tier.

**AC:** A fixture PR edits `scripts/oversight/validators/rn_calculator.py` so that it returns
score 0, and also adds a high-RN function. The computed tier on both paths still reflects the
added function.

### REQ-6: One file set: the PR's own change

- Both sides must score the PR's own change: merge base to head, the same set
  `gh pr diff --name-only` reports.
- Files changed only on the base branch must not enter the scoring (VF-5). Files deleted at head
  contribute nothing (current behavior, `:215-216`).

**AC:** A fixture branch that is behind its base, where the base changed a high-RN file the PR
does not touch, produces the same tier as the same PR rebased.

### REQ-7: A function the PR changes is scored in full, with no discount

- Any function or method the PR adds or modifies is scored in its **entirety**, at its head
  content. RN is a property of the whole function, not of the changed lines.
- A move or rename of a function counts as a change.
- A changed `.py` file that cannot be parsed fails closed (REQ-4). It is not skipped.
- Diff risk must never score lower than today's whole-file computation would score the same
  added or modified code on its own.

**AC:**
- (a) A PR that changes one line inside the RN-32 function scores that function's RN in full.
- (b) A PR that adds a new RN ≥ 15.6 function computes at least the tier ESC-1's ruling assigns
  to it, which today is CRITICAL.

### REQ-8 (pending ESC-2): Inherited risk alone does not raise the tier

Code in regions the PR does not change must not, by itself, raise the ceiling tier. The proposed
default unit is the function (ESC-2): a function is in scope if any changed hunk intersects its
span. Module-level code in a changed hunk is in scope.

**AC:** The #1907 fixture (an untouched RN-32 function plus a trivial change elsewhere in the
file) does not compute CRITICAL from the RN dimension.

### REQ-9 (pending ESC-1): Composition of the single tier

The proposed default (ESC-1 option B) is:

  ceiling tier = max(composite tier with floors applied, RN-mapped tier of in-scope functions)

Both terms are computed on the REQ-6 file set and the REQ-8 scope. This keeps today's gate as a
backstop for genuine diff risk, while no longer charging the PR for inherited risk. Floors
(`diff_size`, `static_analysis`, task-class) are **applied** to the tier, not just surfaced
(VF-3).

**AC:** A test covers each term winning:
- a composite-driven HIGH with a low RN;
- an RN-driven CRITICAL with a low composite;
- a floor-driven HIGH.

### REQ-10: The result explains itself

Gate output and the overseer's verdict body must both report:
- the tier and the ceiling;
- each contributing term (composite, RN-in-scope, structural, floors), with its value;
- the in-scope files and the function that set the RN term (`file:line name RN=n`);
- any fallback taken (REQ-4).

A human must be able to see why the two sides agree, and what set the tier.

**AC:** The gate's stdout for the #1907 fixture names the scope and the function that set the RN
term, and states that the RN-32 function is out of scope.

### REQ-11: No stale or foreign local summary

- No caller may use a precomputed `summary.json` that is not bound to the PR head SHA being
  judged (VF-8).
- If a precomputed result is used at all, it must carry the head SHA, it must be rejected on a
  mismatch, and its `tier_floor` must be honoured.

**AC:**
- (a) A summary for another head SHA is ignored, and the tier is recomputed or the call fails
  closed.
- (b) A summary with `tier: MEDIUM` and `tier_floor: HIGH` yields HIGH.

### REQ-12: Regression suite

- `tests/framework/test_require_tier_ceiling.py` (31 tests) keeps passing. A test may change only
  where it encodes whole-file semantics that REQ-8 deliberately changes, and each such change is
  named in the PR body.
- The TD-1657 wrapper tests (W4, W8-W14) pass unchanged.

### Non-functional

- **NFR-1:** The CI gate gains no new runtime dependency beyond what the trusted-base checkout
  and the runner already provide. It makes no network calls beyond the `gh` API it uses today.
- **NFR-2:** The result is deterministic: the same head SHA and merge base give the same tier on
  re-run. Dimensions whose output depends on time or network state (ESC-3) must not make the two
  sides disagree.
- **NFR-3:** The gate's runtime stays within the existing bounds (`rn_calculator` timeout 60 s,
  `:251`). It is re-run on every review event (`rerun-gate-checks.yml`).
- **NFR-4:** The PR size policy applies (≤15 files, ≤10 commits per slice).

---

## 3. Out of scope

- Hunk scoping for **gates**, which is pass/fail on violations. That is #1791, and it is blocked
  on a human ruling.
- Where the *worker's* self-reported tier enters the pipeline (#1427). REQ-1 and REQ-5 are
  compatible with #1427 and reduce its surface, but this document does not close it.
- Re-tuning `WEIGHTS`, `TIER_THRESHOLDS`, `_SCORE_HIGH_THRESHOLD` or `OVERSEER_CEILING`.
- Refactoring `test_pipeline_subshell_shows_nested_argv_child_benign_1265` to lower its RN. This
  would relieve the hot file in the meantime, but it treats the symptom (see recommendations).

---

## 4. Option compatibility (the architecture choice is the architect's)

| Requirement | Option 1 (gate scores changed functions) | Option 2 (one shared computation) | Option 3 (wrapper runs the gate's computation) |
|---|---|---|---|
| REQ-1 one tier | Only if the overseer adopts the same scoping and aggregation (VF-3) | Yes, by construction | Yes for `approve`; REQ-1(c) still needs `overseer.md` |
| REQ-2 both directions | Overseer-higher case not covered alone | Yes | Overseer-lower case only; VF-7 needs more |
| REQ-3 decidable | No, alone | Yes | Yes, if VF-8 is fixed (REQ-11) |
| REQ-5 trusted code | Yes (CI) | Needs care on the overseer side | Yes, if the wrapper loads base-pinned code |
| REQ-8 inherited risk | Yes | Only if the shared computation is scoped | No; it refuses more PRs and fixes nothing |

No single option meets every settled requirement on its own. Option 2 with the REQ-8 scoping, or
options 1 and 3 together with a VF-7 fix, appear to cover the set. The requirements constrain
outcomes only.

---

## 5. Escalations (defaults are pm-agent proposals, not rulings)

**ESC-1: What is the ceiling gate for?** Is it a **re-verification** of the overseer's own tier,
or a deliberately **independent and stricter** backstop? Today it acts as the second: RN-alone,
undiluted. The options:
- **A.** One shared definition (issue option 2): ceiling tier = composite with floors. The gate
  equals the overseer. This **loosens** today's gate: a PR that adds a genuine RN-32 function
  could rate HIGH and be auto-merged.
- **B (default).** Ceiling tier = max(composite with floors, RN-mapped tier of in-scope
  functions), used by both sides (REQ-9). It is never looser than today on diff risk, and it
  agrees by construction.
- **C.** Keep the whole-file gate and add only issue option 3. This stops the dismiss-and-repost,
  but it makes every PR touching `test_hos_cron.py` HUMAN_REQUIRED for good. It does not fix
  VF-7.

**ESC-2: May inherited risk be excluded from the tier?** The human ruled on 2026-10-03 (PR #1956)
that "all gates must be clean, even if pre-existing". #1791 is human-blocked on how far that
ruling extends.
- pm-agent's view is that the ruling governs gate *violations*, while the tier measures the risk
  of *this change*, so REQ-8 does not conflict with it. A worker cannot settle that.
- The default is: exclude inherited risk, with the function as the unit (REQ-8).
- Alternatives:
  - (b) line-level scoping, which discounts partly changed functions and is not recommended
    (REQ-7);
  - (c) no exclusion. Then ESC-1 option C is the only remaining fix.

**ESC-3: Dimensions that CI cannot reproduce.** This applies only under ESC-1 A or B.
- `historical_density` (`issue_query.py`) depends on GitHub issue state and git history, so it
  varies over time. `ip_check` needs ScanCode, and `static_analysis` needs bandit.
- Options:
  - (a) exclude them from the ceiling tier on both sides. This changes the overseer's number;
  - (b) provision them in CI, with a snapshot to keep the result deterministic;
  - (c) the gate re-verifies a head-SHA-bound result that the overseer publishes. This is
    rejected unless REQ-5 can be met, because it trusts an agent-produced artifact.
- No default. The architect should propose one, and it needs a ruling because it changes what
  the ceiling measures.

---

## 6. Suggested slices (for TD to confirm)

All slices are human-gated (protected surfaces).

- **S1.** The shared or scoped tier computation, and the gate switch-over (REQ-1, REQ-4 to REQ-9,
  REQ-11 and REQ-12). Touches `scripts/framework/**`, and possibly `run_validators.sh` and
  `schema.py`.
- **S2.** The overseer pre-post check and the #1426 bypass agreement (REQ-2, REQ-3). Touches
  `pr_review_cli.py`, which is unprotected, and `require_overseer_approval.py`, which is
  protected.
- **S3.** `overseer.md`: name the procedure, and update condition 2 and `:473` (REQ-1(c),
  REQ-10). This is `.claude/agents/**`, authored by the top-level session per CLAUDE.md.

---

## 7. Traceability

| Requirement | Source |
|---|---|
| REQ-1 | #1909 "two authorities"; VF-3, VF-4 |
| REQ-2 | #1907 sequence (VF-9); VF-7; #1426, #1657 |
| REQ-3 | #1909 "not decidable … before it posts"; VF-6; TD-1657:168 |
| REQ-4 | #973; the pm-agent fail-closed mandate |
| REQ-5 | VF-10; #1427 |
| REQ-6 | VF-5 |
| REQ-7, REQ-8 | #1909 option 1; VF-2; ESC-2 |
| REQ-9 | ESC-1; VF-3 floors |
| REQ-10 | Overseer executive-summary contract; auditability |
| REQ-11 | VF-8; #1909 option 3 |
| REQ-12 | #973, #1657 regression suites |

## Recommendations (not requirements)

- If the human wants relief while this design proceeds, consider filing a separate issue to
  refactor the RN-32 test function in `test_hos_cron.py`. That stops the #1907 repeat on that one
  file, but it is a workaround, not this fix.

## Escalation flag (CORE self-flag)

RISK: HIGH. This changes the computation behind a CORE safety threshold and two required checks.
A mistake in the scoping or aggregation could admit a PR whose diff is genuinely above the
ceiling.
CONFIDENCE: HIGH on VF-1 to VF-3 and VF-5 to VF-10, each verified by line, and VF-2 reproduced by
running `rn_calculator.py`. MEDIUM on VF-4: the overseer's actual procedure is observed practice,
and the agent definition does not specify it.
Change classification: **structural**.

## Human Review Required

- ESC-1 and ESC-2 need rulings, or acceptance of their defaults, before S1 starts.
- ESC-3 needs a ruling if ESC-1 resolves to A or B.
- Every slice touches protected surfaces and needs human approval.
