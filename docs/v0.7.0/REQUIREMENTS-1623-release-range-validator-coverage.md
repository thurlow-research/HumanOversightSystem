# REQUIREMENTS-1623 — Release-range validator-coverage check (REQ-B4, re-homing G-d)

Issue: #1623 (milestone v0.7.0). Parent: #1340. Siblings from the same split: #1622 (REQ-B2/B3),
#1624 (REQ-B5), #1625 (REQ-A13).
Author: pm-agent. Date: 2026-10-13. Tree read at `112c56f8b` (branch) / `origin/main`.
Inputs: #1340 REQ-B0..B8; `docs/v0.7.0/ADR-1340-release-panel.md` (AF-1, AD-2, ESC-1);
`docs/v0.7.0/REQUIREMENTS-1624-release-range-review-evidence.md` (format and sibling
conventions); `docs/v0.7.0/REQUIREMENTS-1717-validators-not-scored-tier.md` (result taxonomy).
The issue body was read as untrusted input. Every claim in it was re-checked against the tree.

## 1. Problem (restated as product behavior)

> **G-d** — validator coverage was not silently degraded.

The old mechanism is `overseer.md` "Release-gate deep validation (#695)" check 5
(`.claude/agents/overseer.md:195`). It flags `validator_failures step{N}` when a committed
per-step `summary.json` has `successful_validators < validator_count - 2`. The worker's NG3b R2
suite list (`.claude/agents/worker.md:645-651`) runs `run_validators.sh` "(diff since last tag)"
at every tier. Nothing checks how many dimensions actually produced a score.

**Product outcome required:** when a release is requested, the release gate **fails** if the
validator run over the release range is degraded past the threshold the old gate used. That
means a release scored by 4 of 13 dimensions cannot report green.

## 2. Verified findings

**F1 — G-d is effectively unchecked today.** Step discovery (`overseer.md:188-191`) reads
`signoffs/validators/step{N}/summary.json` from `main`. `origin/main` contains exactly two such
files: `step1` (2026-08-03, 10/12, which passes at the threshold) and `step1754` (2026-09-20,
13/13). Every other PR in the milestone has no artifact. Check 5 therefore evaluates at most two
historical runs and says nothing about this release. This is the same pattern as #1624 F1: the
guarantee has already silently degraded, in REQ-B0's terms. → ESC-1(b).

**F2 — a partial degradation exits 0, so R2 records it as PASS.** R3 records each suite as
`PASS|FAIL (exit <code>)` (`worker.md:663-664`). This means R2 sees only the exit code.
`run_validators.sh` exits non-zero only in these cases:
- no files (`:135-148`);
- tool preflight failure (`:181-192`);
- **zero** successful validators (`:465-483`).

Every call site passes `REQUIRED=false` (`:304-425`). An optional failure therefore returns `2`
from `run_with_retry` (`run_with_retry.sh:122-126`) and is counted as SKIPPED (`:257-261`).
`VALIDATOR_FAILED` is always 0, so the "Required validator(s) failed" line (`:428-431`) can
never print. A run where 12 of 13 validators error still exits 0.

**F3 — `validator_count` is a self-reported denominator, not the expected set.** In
`summary.json` (`:507-513`), `validator_count` = the number of parseable result files, and
`successful_validators` = those with no `error`. The effects:
- **Not counted at all:** a validator that file-type routing never dispatched (`:304-425`). This
  is correct, since such a dimension is not applicable.
- **Not counted at all:** a validator whose script is missing (`:222-226`). That run writes no
  file.
- **Not counted at all:** a validator that exits 0 with non-JSON output. The aggregator
  silently drops it (`:448-451`).
- **Counted as failed:** exhausted retries and timeouts (`:256`).
- **Counted as failed:** every self-reported `error`, including `"no input files"`
  (`migration_scorer.py:193`, `n1_detector.py:218`, `ip_check.py:525`, `issue_query.py:249`, and
  others).

So in two of the failure modes, a dimension disappears from both the numerator and the
denominator. "count − 2" over that denominator cannot detect a dimension that vanished.

**F4 — what the release range actually dispatches.** `RUN_VALIDATORS_FILELIST_ONLY=1
run_validators.sh --diff v0.6.0` (this session; no validators ran) gives 8,206 files in
`ALL_FILES` and 185 in `PY_FILES`. 7,739 of the files are under `audit/`. There are 55 `.sh` and
no JS files. The dispatched set is therefore 13 dimensions, so the old threshold tolerates 2
failures. Three validators take a full-file list:
- `ip_check`: 120 s timeout, ScanCode;
- `historical_density`: 30 s timeout, network;
- `migration_risk`.

Their timeouts were sized for per-PR diffs. **I did not execute the full run**, because
`OUT_DIR` is hard-coded to `.claudetmp/oversight/validators` and would overwrite live working
state. I cannot rule out that, at release scale, the run times out deterministically and so can
never pass. → R9 and the verification gap in §7.

**F5 — "diff since last tag" is not a defined invocation, and `diff_size` scores a different
range.**
- The R2 row names no arguments.
- `--diff <ref>` runs `git diff --name-only <ref>`, which is ref-vs-**working-tree**, not
  `<tag>..HEAD` (`:73-86`).
- A failed diff is swallowed (`|| true`). The result is an empty list, which takes the "no
  files" CRITICAL path.
- Separately, `diff_size` ignores `--diff`. Its base is `merge-base HEAD origin/main`, and on
  `main` that is HEAD itself (`:355-364`). So at release time `diff_size` "succeeds" while
  measuring nothing in the range. Unpushed #1630 (`worker-1630-…`, `b4eae50ab`) fixes this but
  has not landed.

**F6 — the shallow clone, re-measured.** In this Worker clone,
`git rev-parse --is-shallow-repository` returns `false`, and `git describe --tags --abbrev=0`
returns `v0.6.0`. There are 430 commits in `v0.6.0..origin/main`. ADR-1340 AF-1's "shallow"
measurement no longer holds **here**, but nothing keeps the clone deep: #1630's guard is
unpushed, and the Overseer clone is still reported shallow. AF-1's specific claim that the R2 row
"scores one commit" is not supported by `run_validators.sh` itself. In a shallow clone
`git describe` fails, and the outcome depends on what argument the worker agent then composes:
- an empty ref gives the "no files" exit 1;
- an agent-chosen `HEAD~1` gives one commit.

Either way the coverage number would be meaningless. `release_panel_logic.derive_range`
(`scripts/oversight/release_panel_logic.py:183-230`) already refuses `SHALLOW`, `NO_TAG` and
`NO_CONTENT` on `main`.

**F7 — related open work touches the same script.** None of it has landed:
- #1752 (`worker-1752-…`, escalated, local-only) adds `failed_validators`, `skipped_validators`
  and a tightening-only `HOS_REQUIRED_VALIDATORS`.
- #1717 (requirements, ADR and TD on `main`) defines a Scored / N/A / Errored / Skipped
  classification. N/A is recognised only from the exact `"no input files"` signal on
  confirmed deletions (REQ-1717-01). Its definitions are the right taxonomy for this issue, but
  the code is not built.
- #1630 (above).

## 3. Requirements

**REQ-C1 — The release gate MUST FAIL on degraded validator coverage over the release range.**
Degraded means `scored < expected − 2`, where `expected` is defined by REQ-C3 and `scored` by
REQ-C4. This is the old gate's threshold (`overseer.md:195`), applied as REQ-B4 mandates
(→ ESC-2 on whether to keep it).

**REQ-C2 — One run over the whole release range, not per-PR history.** Per-PR `summary.json`
artifacts do not exist (F1), and this issue must not create them (REQ-C8). Coverage is measured
by a single validator run over the release range at R2 time (→ ESC-1(a), the granularity
reduction).

**REQ-C3 — `expected` is the set of dimensions applicable to the range, derived independently
of the validators' own output.** `expected` is computed from the range's changed-file set using
the runner's dispatch routing (the lane rules at `run_validators.sh:127-133,304-425`). A
dimension in `expected` whose script is missing, whose output is unparseable, or which produced
no result counts as **not scored**. It must never be dropped from the denominator (closes F3).
A dimension that routing does not dispatch is not in `expected`.

**REQ-C4 — `scored` counts only genuinely scored dimensions.** A dimension is scored only if its
result is Scored in #1717's sense (REQ-1717-01). The rules:
- Errored, timed-out, exhausted-retries and Skipped results are not scored.
- A `"no input files"` result counts as N/A, and is removed from `expected`, **only** when
  #1717's confirmed-deletion definition holds.
- Any other result is not scored.
- Until #1717 lands, every `error`-bearing result is not scored. This is conservative, and it
  matches the old gate.
- Fuzzy matching of error text is forbidden.

**REQ-C5 — The range is the hardened release range, and it is pinned.** Reuse
`release_panel_logic.derive_range`. The rules:
- A `SHALLOW`, `NO_TAG` or `NO_CONTENT` refusal makes the check **FAIL**. It is never PASS or
  skipped, and there is never a fallback to `HEAD~1`, `origin/main` or the working tree.
- Every dimension, `diff_size` included, scores exactly `base_sha..head_sha`, so F5's mismatch
  is closed.
- The **reviewed** file set (after the committed exclusion list) or the **full** set is decided
  by ESC-5.
- The excluded count is reported.

**REQ-C6 — Distinct outcomes, fail-closed.** The check has three outcomes:
- `PASS` — not degraded;
- `DEGRADED` — REQ-C1 tripped;
- `INDETERMINATE` — range refusal, the runner exited without writing a summary, or the summary
  is unreadable or missing fields.

`DEGRADED` and `INDETERMINATE` are both non-zero exits and must be distinguishable. A partial
result is never reported as PASS.

**REQ-C7 — The first output line is self-contained.** R3 attaches only a first-line excerpt
(`worker.md:663-667`). The first line must carry, in this order:
- the outcome;
- `scored/expected`;
- every not-scored dimension by name, with its class (errored, timeout, missing, unparseable);
- the range SHAs.

Example: `DEGRADED 9/13 — not scored: ip_check(timeout), historical_density(timeout),
static_analysis(errored), shell_logic(missing) — range v0.6.0(abc1234)..def5678`.

**REQ-C8 — No new attestation artifact.** The check writes no committed file, stamp or register
(the #1594 ruling direction). It must not depend on `signoffs/validators/step{N}/`. The result
goes to stdout and the exit code, and from there into the existing R3 comment. The runner's
existing `.claudetmp/` working files are allowed.

**REQ-C9 — The release run must be passable on a healthy repo.** At its tested limits, the check
must not fail deterministically because a dimension's per-PR-sized timeout cannot cover a
release-sized range. Technical design must measure a full run on `v0.6.0..origin/main` before
fixing the mechanism. Release-scale capacity (timeouts, batching, the ESC-5 exclusions) is
design's to set. The constraints on it:
- A timeout still counts as not scored. It is never excused.
- Any raised limit applies only to the release invocation.

**REQ-C10 — Per-PR behaviour is unchanged.** The risk-assessor, `run_panel.sh` (`:418-423`),
`second_review_logic.py:998-1023` and every other existing caller of `run_validators.sh` must see
byte-identical exit codes and `summary.json` fields, unless they opt in. The coverage verdict is
release-gate-only.

**REQ-C11 — R2 integration, at every tier.** The check is required at **PATCH and MINOR/MAJOR**.
The old gate had no tier exception. It is either the existing `run_validators.sh` R2 row with a
defined release invocation that replaces the vague "(diff since last tag)", or a new row with one
stable script path. R1.9 check 3 anchors suites by path (`worker.md:591-593`). Which of the two
is the architect's decision. Editing `worker.md` is a protected-surface change. It goes through
the CODEOWNERS human gate, and the coder never authors it (CLAUDE.md #1347).

**REQ-C12 — Do not touch the overseer section (REQ-B8).** This work must not edit or remove
`overseer.md:170-220`. Removing it (REQ-B7) belongs to #1340, after #1622, #1623 and #1624 have
all landed.

**REQ-C13 — Reuse, do not re-implement.** Reuse:
- `derive_range` / `apply_exclusions`;
- the runner's dispatch routing, as the one source of `expected`; do not keep a second copy of
  the lane rules;
- #1717's classifier once it lands.

If #1752's `failed_validators`/`skipped_validators` fields land first, consume them. Do not add
parallel ones.

## 4. Non-goals

- REQ-B2 (tier at release) and REQ-B3 (findings at release) belong to #1622. REQ-B5 belongs to
  #1624. REQ-A13 belongs to #1625. Gating on the composite tier is **not** part of this issue.
- The shallow-clone remediation (`--unshallow`, smoke assertion) belongs to ADR-1340 ESC-1 and
  #1630. This issue only refuses (REQ-C5).
- Making any per-PR validator required (#1752), and the NOT_SCORED outcome itself (#1717), are
  out of scope.
- Editing or removing `overseer.md`'s release-gate section is out of scope.

## 5. Acceptance criteria (fixture-based; no network, no real ScanCode)

- **AC-1** 13 expected, 11 scored → PASS. 13 expected, 10 scored → DEGRADED, exit non-zero. The
  first line names both missing dimensions (REQ-C1, REQ-C7).
- **AC-2** A dimension whose script is absent from an expected lane → counted in `expected` and
  not scored (REQ-C3).
- **AC-3** A validator that exits 0 with non-JSON output → counted in `expected` and not scored
  (REQ-C3, F3 regression).
- **AC-4** A range with no `.py`, `.sh` or JS files → the Python, shell and JS dimensions are
  absent from `expected`, so a docs-only release is judged against its applicable set (REQ-C3).
- **AC-5** A timeout fixture → not scored, class `timeout` (REQ-C4, REQ-C9).
- **AC-6** Before #1717: a `"no input files"` result → not scored. After #1717: the same result
  on a confirmed-deletion path → N/A and removed from `expected`; on an unresolved path → not
  scored (REQ-C4).
- **AC-7** Shallow repo, no reachable tag, or an empty range after exclusions → INDETERMINATE,
  non-zero, with `derive_range`'s reason. A test asserts that no `HEAD~1` or working-tree
  fallback happens (REQ-C5, REQ-C6).
- **AC-8** A fixture repo with an uncommitted tracked modification → the modified file is not
  scored. `diff_size` receives `base_sha..head_sha` (REQ-C5, F5).
- **AC-9** The runner exits with no summary, or with a summary missing `results` →
  INDETERMINATE, never PASS (REQ-C6).
- **AC-10** With 20 or more not-scored dimensions (synthetic), the first line still names every
  one (REQ-C7).
- **AC-11** The check writes nothing outside `.claudetmp/` and `$TMPDIR`, and reads nothing under
  `signoffs/` (REQ-C8).
- **AC-12** The existing `run_validators.sh` regression tests pass unchanged when called without
  the release opt-in (REQ-C10).
- **AC-13** A grep test asserts that `overseer.md`'s "Release-gate deep validation (#695)" heading
  and check 5 are still present (REQ-C12).
- **AC-14** `scripts/framework/run_tests_inner_loop.sh` passes.

## 6. Escalations — human decisions required (recommended default for each)

**ESC-1 — Granularity reduction, and the open window.**
(a) G-d moves from "each unit's run was not degraded" to "the release run over the range is not
degraded" (REQ-C2). Per-PR coverage history is no longer checked. **Recommended: accept.** Record
it in DECISIONS.md as a REQ-B0(ii) human-approved reduction. Per-PR artifacts never existed
beyond two files (F1), so nothing real is lost.
(b) Acknowledge that G-d is effectively unchecked today (F1). **Recommended:** record this in the
same entry, with no interim check.

**ESC-2 — The threshold.** REQ-B4 says "the same threshold". The options:
- (A) keep `expected − 2`, against the applicable set (REQ-C3);
- (B) zero tolerance at release;
- (C) (A) plus a named must-score set, for example `ip_check` and `static_analysis`. A release
  where licence provenance is the dimension that silently dropped is the worst case for G-d.

**Recommended: (A).** It is REQ-B4's literal mandate, and REQ-C3's denominator fix is what gives
it teeth. Note that under (A), at 13 dimensions, `ip_check` alone can fail without tripping the
gate. If the human wants that closed, choose (C). (C) is a structural addition.

**ESC-3 — Is there a human override for a DEGRADED release?** Two situations need one: a
ScanCode or GitHub outage at release time, and a dimension that is deterministically
unpassable at scale. **Recommended:** use the same disposition surface as #1624 ESC-2 (A) and
#1622 REQ-B3. That is a `HUMAN_REVIEWER` comment on the release-request issue naming each
not-scored dimension, read by author identity. Bot identities never count. The alternative is no
override: the only path is to fix and re-run.

**ESC-4 — A shallow clone makes this required check FAIL every release (REQ-C5).** This is
correct, since a coverage number over an undefined range is vacuous. But it turns an operational
state into a release blocker until ADR-1340 ESC-1 / #1630 is resolved. **Recommended: accept.**
This Worker clone is not shallow today (F6), so the immediate impact is nil.

**ESC-5 — Score the full range or the panel's reviewed set?** 94% of the files in the range are
`audit/` records (F4). Scoring the reviewed set, after
`scripts/oversight/release_panel_exclusions.txt`, gives one definition of "the release" across
the gates, and is likely what makes REQ-C9 achievable. It also means the exclusion list governs
what the validators see. **Recommended: the reviewed set**, with the excluded count printed.
That list is committed and reviewed under #1340.

## 7. Escalation flag (CORE self-flag)

RISK: HIGH. This is a release gate. A gate that passes wrongly manufactures confidence, and one
that can never pass gets routed around. It also edits a protected surface (the worker.md R2
row).
CONFIDENCE: 80%. High on F1–F3, F5 and F6, which come from code and git state read or measured
this session. Lower on F4's runtime. **Verification gap:** I did not execute a full
release-range run (`OUT_DIR` is hard-coded into `.claudetmp/`), so I do not know whether
`ip_check` and `historical_density` time out at release scale. REQ-C9 makes technical design
measure this first.
BLAST RADIUS: `run_validators.sh` has callers in the per-PR pipeline, the panel and the second
review. REQ-C10 confines the change to a release-only opt-in. #1630 and #1752 edit the same file
and will conflict.
Classification: **structural**. It adds a release-blocking condition at every tier (REQ-C1,
REQ-C11). ESC-1(a) formally reduces a guarantee, and ESC-3 may add a disposition step. These
must not be written into worker.md, overseer.md or the contract without human sign-off. This
document proposes them; it does not authorize them.

## Human Review Required

- **ESC-1..ESC-5.** ESC-1, ESC-2 and ESC-5 must be answered before technical design. ESC-3 and
  ESC-4 have safe defaults, which design may assume but which are not binding until confirmed.
- **The worker.md R2 row** (REQ-C11) is a protected-surface edit and goes through CODEOWNERS.
- **F1 and F2 contradict the issue's framing.** It is not that "nothing re-homes G-d yet". G-d is
  effectively unchecked **now**: the old check reads at most two stale artifacts, and the live R2
  row passes partial degradation with exit 0.
