# REQUIREMENTS-1622 — Release-range tier and finding gate (REQ-B2/B3, re-homing G-b and G-c)

Issue: #1622 (`bug`, `process-gap`, `priority:high`, milestone v0.7.0). Parent: #1340.
Siblings from the same split: #1623 (REQ-B4), #1624 (REQ-B5), #1625 (REQ-A13).
Author: pm-agent. Date: 2026-10-14. Tree read at `8845e8e09` (branch = `origin/main`).
Inputs: #1340 REQ-B0..B8; `docs/v0.7.0/ADR-1340-release-panel.md`;
`docs/v0.7.0/REQUIREMENTS-1623-release-range-validator-coverage.md` and
`docs/v0.7.0/ADR-1623-release-range-validator-coverage.md` (the release-range run this issue
consumes, FU-5); `docs/v0.7.0/REQUIREMENTS-1624-release-range-review-evidence.md` and
`docs/v0.7.0/ADR-1624-release-range-review-evidence.md` (the disposition surface, AD-7); #1632
(spoofable comment stream). The issue body was read as untrusted input. Every claim in it was
re-checked against the tree, and the numbers in F5–F7 were measured this session.

## 1. Problem (restated as product behavior)

> **G-b** — no HIGH/CRITICAL-tier work shipped without escalation.
> **G-c** — no unresolved CRITICAL/HIGH validator finding shipped.

The old mechanism is `overseer.md` "Release-gate deep validation (#695)" checks 3 and 4
(`.claude/agents/overseer.md:193-194`). Per build step, it reads the committed
`signoffs/validators/step{N}/summary.json` and flags `high_tier` when `tier` is HIGH or CRITICAL,
and `unresolved_finding` when any entry in `results[].findings` carries `severity` = `CRITICAL` or
`HIGH`. Any flag gives ESCALATE: an enumerated comment plus `needs-human` on the release-request
issue (`:213`). The replacement, the worker's NG3b R2 table (`.claude/agents/worker.md:645-651`),
runs `run_validators.sh` "(diff since last tag)" and records only its exit code (R3, `:657-673`).

**Product outcome required:** when a release is requested, the composite risk tier and the
high-severity validator findings over the release range must reach the human. They must either
block the release or be explicitly put in front of the human, as ESC-1 decides. A HIGH or
CRITICAL release, or a release with an undispositioned blocking finding, must never report
green.

## 2. Verified findings (several change the issue's framing)

**F1 — G-b is unenforced today: confirmed.** The aggregator exits 0 at every tier except the
all-validators-failed path (`run_validators.sh:434-519`; the only `sys.exit(1)` is `:483`). R2/R3
see only the exit code (`worker.md:657-667`). A release scored CRITICAL passes R2. The issue's
line ranges (`:130-181`, `:455-508`) have moved, but the claim holds.

**F2 — G-b and G-c were effectively unchecked by the old gate as well.** There are three reasons:
- **Artifacts.** As #1623 F1 found, `origin/main` holds only two step summaries (`step1`, `step1754`).
- **Check 3 reads `tier` only, not `tier_floor`.** `step1754` has `tier=MEDIUM` and
  `tier_floor=HIGH`, and check 3 did not flag it. So the old G-b was a composite-tier guarantee.
  This bears directly on ESC-2.
- **Check 4 can never fire.**
  - It reads `results[].findings`, and only `rn_calculator(_js)` populates `findings`
    (`rn_calculator.py:322`). Those entries carry **no `severity` key**. Both committed artifacts
    confirm this: 21 and 46 `findings`, all with severity `None`.
  - Every other validator puts its located items in `evidence` (`make_finding`,
    `schema.py:13`).
  - Severities are **lowercase** (`"high"`, `"medium"`), and check 4 compares against uppercase
    `CRITICAL`/`HIGH`.
  - **No validator emits a `critical` severity.** `migration_scorer.py:116` maps a CRITICAL op to
    `"high"`.

In REQ-B0's terms, G-c has never been enforced. → ESC-8.

**F3 — "composite tier" has five hard-coded copies, and the named source is the one nothing
uses.**
- `schema.TIER_THRESHOLDS` (`schema.py:84-89`) is read by no code path.
- `schema.score_to_tier` (`:105-114`) hard-codes 0.30/0.55/0.78 again.
- The aggregator uses its own `TIERS` list (`run_validators.sh:487`).
- `require_tier_ceiling._score_to_tier` (`scripts/framework/require_tier_ceiling.py:140-154`) is a
  deliberate mirror.
- `gate_compliance.py:33` holds a constant.
- No test pins their parity (`grep -rl TIER_THRESHOLDS tests/` → none).

A hazard exists as well. `TIER_THRESHOLDS["CRITICAL"] = (0.78, 1.00)` is commented as
hi-exclusive. A naive "lo ≤ score < hi" lookup would therefore map the fail-closed composite 1.0
to **no tier**. → REQ-T2.

Both `schema.py` and `run_validators.sh` are protected surfaces
(`scripts/framework/protected_surfaces.txt`).

**F4 — the composite ignores errored validators.** `run_validators.sh:458-464` and
`schema.composite_score` skip errored results from both the numerator and the denominator. A
run where the high-scoring dimensions failed therefore yields a *lower* tier. A tier verdict over
a degraded run (#1623) understates risk. → REQ-T6.

**F5 — `diff_size` floors every release to HIGH by construction.**
- The floor fires at more than 400 changed lines or more than 15 files (`diff_size.py:42-43`,
  `:160-166`).
- `derive_range()` this session gives `v0.6.0`, 8,208 files in range, 7,752 excluded and **456
  reviewed**.
- Under #1623 AD-3, diff_size scores `base..head` restricted to the reviewed set. 456 files is
  more than 15, so `tier_floor=HIGH` on every realistic release.
- `static_analysis` (`:213`) and `static_analysis_js` (`:157`) also emit `tier_floor=HIGH` when a
  bandit HIGH or semgrep ERROR is present. → ESC-2.

**F6 — the composite tier itself is likely HIGH on every release (partial measurement).**
- I ran 7 local validators over the 185 reviewed `.py` and 55 `.sh` files. The run was read-only
  and wrote output to `/tmp/claude/`.
- Scores: `risk_number` 1.0, `complexity` 1.0, `static_analysis` 1.0, `shell_logic` 0.9,
  `hallucination` 0.67, `function_metrics` 0.02, `portability` 0.0.
- The weighted partial composite is 0.76 over those weights. Assuming `n1_queries` and
  `migration_risk` score 0, it is about 0.58 (**HIGH**) before `historical_density`, `ip_check`
  and `prompt_ambiguity`, which I did not run (network or ScanCode).
- The cause: max-type dimensions (`max_rn` = 289.9, `max_cyclomatic` = 89) saturate on any
  release-sized set. A per-PR-calibrated composite therefore says little at release scale.
- **Verification gap:** this is not a full run. #1623 S0 is the full measurement. → ESC-1.

**F7 — the emitted finding set is a truncated sample, and its population is large.**

In the same partial run:

| Dimension | Shown in `evidence` | Real count |
|---|---|---|
| `risk_number` | 5 `high` items (top-5 cap, `rn_calculator.py:286-295`) | 206 functions with RN ≥ 8 |
| `complexity` | 5 `high` items (top-5 cap, `complexity_metrics.py:124-131`) | `high_complexity_functions` = 206 |
| `shell_logic` | 36 `high` and 13 `medium` (uncapped) | — |

The `[:10]` caps elsewhere work as follows:
- `static_analysis` caps bandit HIGH at `[:10]` (`:157`), but `raw_value.bandit_high_count` holds
  the full count.
- `ip_check` caps at `[:10]` (`:452-460`), but keeps `raw_value.high_count`.
- `migration_scorer` keeps `critical_count` and `high_count`.
- `issue_query` caps at `[:10]` and carries no count.

So "any HIGH finding", read from `evidence`:
- gives roughly 46 or more items per release, before network dimensions;
- is mostly whole-file structural metrics on code that predates the range, since validators score
  whole files, not changed lines;
- **cannot see** items past each cap.

→ ESC-3, ESC-6.

**F8 — #1623 already owns the release-range run.** ADR-1623 owns the pieces that #1622 would
otherwise duplicate:
- the release-mode invocation (AD-3): range pinned through `derive_range`, content pin,
  `.claudetmp/oversight/validators-release/`, budget (AD-4);
- per-runner-name outfiles plus a dispatch manifest (AD-2);
- the explicit hand-off in FU-5: "tier and findings at release should read
  `…/validators-release/summary.json` from this run. They should not start a second release-scale
  run."

ADR-1623's non-goals exclude tier gating. The boundary is drawn in §3 (REQ-T1) and §4.

**F9 — the disposition surface and its spoofing hazards already have a design.**
- ADR-1624 AD-7 (reused by ADR-1623 S3): `HUMAN_REVIEWER` comments on the release-request issue,
  where `user.type == "User"` and the login is not in `BOT_ACCOUNTS`.
- The **unedited rule** (AF-4): an account with `issues:write`, including the worker App, can
  edit a human's comment.
- An exact-item grammar with no wildcards.
- #1632: `query_issues.sh --comments` emits an author/body text stream that any commenter can
  forge with a fake `--- <login> @ <ts> ---` line. `--comments-json` now exists
  (`bootstrap/query_issues.sh:54,127`).
- A disposition is the first PASS-bearing claim this gate would read back from comments. It must
  therefore never come from the text stream.

**F10 — every release already reaches a human, so "route to `needs-human`" must mean something
more.**
- R4 adds `needs-human` unconditionally on all-pass as the authorization handle (`worker.md:693-708`).
- R5 requires a CODEOWNER's three-signal authorization.
- `worker.md` contains no reference to the overseer's CLEARANCE comment. So the old gate's
  ESCALATE had force only as *disclosure* before the human authorized.

A requirement satisfied by "R4 adds `needs-human`" would therefore be vacuous. Routing to the
human must either:
- **block** (R3 FAIL until a disposition is recorded); or
- **force disclosure at the decision point** (the tier and its reason in the R4 authorization
  comment).

→ ESC-1.

## 3. Requirements

### Boundary and input

**REQ-T1 — Consume #1623's release-range run; do not start a second one.** The tier and finding
verdicts are computed from the release-mode run that #1623 defines: ADR-1623 AD-2/AD-3, the
`.claudetmp/oversight/validators-release/` outfiles and its `summary.json`. This issue must not
re-derive the range, re-implement the scope or content pin, invoke `run_validators.sh` itself
over the range, or change the runner. If technical design finds a field it needs is missing from
that run, it is added in #1623's runner release mode, behind the release opt-in, under #1623's
REQ-C10 byte-identity constraint. It is not added as a parallel mechanism.

**REQ-T2 — The tier is derived from `schema.TIER_THRESHOLDS`, by lower bound, from the run's
`composite_score`.**
- tier = the highest tier whose `lo` ≤ `composite_score`. So 1.0 → CRITICAL, and every boundary
  value maps as `score_to_tier` documents: 0.30 → MEDIUM, 0.55 → HIGH, 0.78 → CRITICAL.
- No new numeric literal may appear (REQ-B2).
- The verdict must not trust `summary.tier`, which comes from the aggregator's own copy (F3). It
  reports `INDETERMINATE` if `summary.tier` disagrees with the tier derived from
  `TIER_THRESHOLDS` (copy drift).
- `composite_score` must be a finite non-bool number in [0, 1]. Otherwise the verdict is
  INDETERMINATE.

**REQ-T3 — The gated tier is the composite tier (pending ESC-2).** `tier_floor` values are
reported on line 1 for information. They do not gate, unless ESC-2 rules otherwise. This matches
REQ-B2's wording ("composite tier") and the old check 3 (F2).

### Verdicts

**REQ-T4 — Tier verdict.** The outcome by composite tier:
- LOW or MEDIUM → PASS.
- HIGH or CRITICAL → the ESC-1 outcome. The recommended default:
  - HIGH → `PASS-DISCLOSED` (REQ-T8);
  - CRITICAL → FAIL unless tier-dispositioned (REQ-T9).
- Whatever the ruling, a HIGH or CRITICAL release never yields a plain PASS that leaves R4's
  authorization comment silent about the tier.

**REQ-T5 — Finding verdict.**
- **Blocking set.** The gate computes the set of blocking findings in the run. The finding classes
  are fixed by ESC-3. Severity matching is case-insensitive over `high` and `critical`, and reads
  both `evidence` and `findings`. Fuzzy matching of message text is forbidden.
- **FAIL** if any blocking finding is not dispositioned (REQ-T9).
- **PASS** only if every blocking finding is dispositioned or none exist.
- A dispositioned finding stays visible as DISPOSITIONED. It never silently becomes a pass.

**REQ-T6 — Bound to one complete run.** Each of the following gives INDETERMINATE, never PASS:
- #1623's coverage verdict for the same run is not PASS (F4);
- the run's range SHAs differ from the current release candidate (`git rev-parse HEAD`);
- the run's outputs are missing or unreadable;
- the run predates the candidate head.

The case where coverage is DEGRADED but human-dispositioned under #1623 ESC-3 is decided by ESC-7.

**REQ-T7 — Completeness against counts (F7).** For each dimension in the blocking classes that
exposes a total count (`bandit_high_count`, `ip_check.high_count`, `migration_risk.critical_count`
and `high_count`, or the equivalent), the gate compares the count with the itemised entries. The
excess is a blocking item of its own, `<runner>: <k> not itemised`. It is never ignored. How the
excess is dispositioned is ESC-6. A blocking-class dimension with no count field is treated as
complete only if its list is uncapped in code. Technical design must verify this per dimension
and record it.

### Human surface

**REQ-T8 — Disclosure at the decision point.** Any HIGH or CRITICAL tier, and every DISPOSITIONED
item, must appear in the R4 authorization comment the human reads before self-assigning. It must
not appear only in an R3 failure comment or in `.claudetmp/`. If ESC-1 selects `PASS-DISCLOSED`,
R2/R3/R4 gain a third suite state, and R4's comment carries the suite's first line verbatim. That
is a `worker.md` change.

**REQ-T9 — Disposition: one surface, identity-bound, pinned.**
- **Surface.** A disposition is a comment on **this release-request issue**, using the reader and
  rules of ADR-1624 AD-7 (shared with #1623 S3; there is one reader, and this issue must not add a
  second). The product constraints:
  1. **Author.** `user.login` equals `HUMAN_REVIEWER` from `machine-accounts.env`
     (case-insensitive), `user.type == "User"`, and the login is not in `BOT_ACCOUNTS`. The
     human-proxy bot `scottthurlow-claude[bot]` never counts.
  2. **Structured transport.** Comments are read only through a structured, paginated JSON read:
     `scripts/automation/lib/github.py` or `query_issues.sh --comments-json`. Never through the
     `--comments` text stream (#1632, F9). A page cap or a malformed payload gives INDETERMINATE.
  3. **Unedited.** `updated_at == created_at`. An edited comment is ignored and reported
     (ADR-1624 AF-4).
  4. **Exact items.** Each disposition names exactly one or more gate-printed identifiers:
     `tier:<HIGH|CRITICAL>`, or `finding:<id>` where `<id>` is the identifier the gate printed for
     that finding. Wildcards and "all" are not accepted (but see ESC-5). An empty reason is not
     accepted.
  5. **Pinned to the candidate head.** A disposition is honoured only for the release-candidate
     head SHA it names, as a full 40-hex SHA (ESC-4). A new candidate head requires fresh
     dispositions.
  6. **Read at gate time.** A disposition is never copied into a committed file, stamp or register
     (the #1594 direction).
- **Finding identifiers.** The gate assigns them. They must be deterministic for the same run
  content, and must be derived from the runner name plus the finding's location and rule. They
  are never derived from the validator's self-reported `dimension` (ADR-1623 AF-2), and never
  from free message text alone.

**REQ-T10 — Output contract.** This mirrors ADR-1623 AD-5 and ADR-1624 AD-6.
- **Line 1** is self-contained, because R3 attaches only line 1. It carries:
  - the outcome;
  - the composite score and the derived tier;
  - the `tier_floor` values (informational);
  - the counts of blocking findings, undispositioned and dispositioned;
  - every undispositioned identifier, with no cap;
  - the range SHAs.
- Line 1 contains identifiers, counts and SHAs only. It never contains file paths or message text,
  which are attacker-influenced.
- Later lines hold one row per blocking item, with sanitised path, line, runner, rule and
  disposition URL.
- **Exit codes:** 0 PASS, 1 FAIL, 2 INDETERMINATE or usage error, and a distinct code for
  `PASS-DISCLOSED` if ESC-1 adopts it. The codes do not overlap. An internal exception never exits
  1.

### Integration

**REQ-T11 — R2 integration, at every tier.** The check is required at **PATCH and MINOR/MAJOR**.
The old gate had no tier exception.
- It is one stable script path that R1.9 check 3 can anchor. Whether it is a new R2 row or folds
  into #1623's `release_validator_coverage.sh` row is the architect's call.
- Either way, REQ-T6's single-run binding must hold. A separate row can be carried forward
  independently by R1.9 check 3, so the binding must be checked, not assumed.
- A disposition comment is a non-bot comment, so R1.9 check 3 already forces a fresh run. R1.9
  needs no change.
- Editing `worker.md` is a protected-surface change. It goes through the CODEOWNERS gate, and the
  coder never authors it (CLAUDE.md #1347).

**REQ-T12 — Per-PR behaviour unchanged.** None of the following may change for any per-PR
caller:
- the per-PR exit codes and `summary.json` of `run_validators.sh`;
- the risk-assessor's tier logic;
- `require_tier_ceiling.py`;
- the overseer's ceiling.

This issue adds no tier-based exit to `run_validators.sh`.

**REQ-T13 — No edit to the overseer section (REQ-B8).** This work must not edit or remove
`overseer.md:170-220`. A grep test pins the presence of checks 3 and 4. REQ-B7's removal belongs
to #1340, after this issue's **arming** slice has merged, together with #1623's and #1624's.
"Landed" in REQ-B8 means armed, as in ADR-1623 §7.

**REQ-T14 — Reuse, do not re-implement.** Reuse:
- `release_panel_logic.derive_range`, only through #1623's run (REQ-T1);
- the AD-7 disposition reader;
- `github.py` for reads;
- `schema.TIER_THRESHOLDS` as the only threshold source.

The tier-threshold parity across the five copies (F3) is **not** fixed here. A parity test is
named as a follow-up (§4), because fixing the copies edits protected per-PR code.

## 4. Out of scope / non-goals

- The release-range run itself: range, scope, content pin, budget, runner release mode, coverage
  verdict (#1623). Review evidence (#1624). REQ-A13 (#1625). The panel (#1340).
- Recalibrating the composite, the weights or the thresholds for release scale (F6), or changing
  any validator's evidence caps (F7). If ESC-1 or ESC-3 cannot be made workable without this, it
  becomes a separate issue.
- Consolidating the five tier-boundary copies (F3), and fixing the overseer's dead check 4 (F2).
  Both are follow-ups. Neither is fixed here.
- Removing or editing `overseer.md`'s release-gate section.
- The #1632 migration of other comment readers.

## 5. Acceptance criteria (fixture-based; no network, no real ScanCode)

The fixtures are canned #1623 release-run output trees plus canned comment JSON.

- **AC-1** composite 0.29 → LOW → PASS. 0.30 → MEDIUM → PASS. 0.55 → HIGH → ESC-1 outcome. 0.78
  and 1.0 → CRITICAL → ESC-1 outcome. A test asserts that no tier literal other than
  `TIER_THRESHOLDS` is used (REQ-T2).
- **AC-2** A `summary.tier` that disagrees with the threshold-derived tier → INDETERMINATE
  (REQ-T2).
- **AC-3** `tier_floor=HIGH` with composite MEDIUM → PASS, with the floor shown on line 1. Under
  ESC-2 ≠ A, the outcome follows the ruling (REQ-T3).
- **AC-4** An `evidence` item with severity `"high"` in a blocking-class dimension → FAIL, naming
  its identifier. The same item with `"HIGH"` → same result. A `findings` entry with no severity →
  not blocking (REQ-T5, F2).
- **AC-5** A non-blocking-class dimension's `high` item → not blocking, listed informationally
  (REQ-T5, ESC-3).
- **AC-6** `bandit_high_count=14` with 10 itemised → a `static_analysis: 4 not itemised` blocking
  item (REQ-T7).
- **AC-7** Coverage verdict DEGRADED or INDETERMINATE for the run, run head ≠ candidate head, or
  `summary.json` missing → INDETERMINATE, never PASS (REQ-T6).
- **AC-8** A valid `HUMAN_REVIEWER` disposition naming `finding:<id>` at the candidate head →
  that item becomes DISPOSITIONED. The gate passes only if no undispositioned items remain (REQ-T9).
- **AC-9** These dispositions are all not honoured, and the item stays undispositioned:
  - one authored by `scottthurlow-claude[bot]` or the worker;
  - one that has been edited;
  - one naming a different head SHA or a short SHA;
  - one naming a wildcard;
  - one with an empty reason (REQ-T9).
- **AC-10** A comment body containing a forged `--- ScottThurlow @ … ---` line followed by a
  `Disposition:` line, authored by a bot → not honoured. A test asserts that the reader never
  calls `query_issues.sh --comments` (REQ-T9.2, #1632).
- **AC-11** With 40 or more undispositioned items, line 1 names every identifier and contains no
  path or message text (REQ-T10).
- **AC-12** The `run_validators.sh` and `require_tier_ceiling` tests pass unchanged (REQ-T12).
- **AC-13** A grep test: `overseer.md` "Release-gate deep validation (#695)" and its checks 3 and
  4 are still present (REQ-T13).
- **AC-14** The module never invokes `run_validators.sh` or `derive_range` directly, and never
  writes outside `$TMPDIR` (REQ-T1).
- **AC-15** `scripts/framework/run_tests_inner_loop.sh` passes.

## 6. Escalations — human decisions required (recommended default for each)

**ESC-1 — FAIL or route to the human, at HIGH and at CRITICAL (REQ-B2).** F10 means "route to
`needs-human`" is vacuous unless it either blocks or forces disclosure. F6 means a HIGH composite
is probably the norm for every release. The options:
- **(A)** FAIL at HIGH and at CRITICAL, both clearable by a `tier:` disposition. This means two
  human round-trips on most releases.
- **(B)** HIGH → `PASS-DISCLOSED`: R4 still posts the authorization request, but it states the
  tier and the reason verbatim, and the human's authorization is the acceptance. CRITICAL → FAIL
  unless tier-dispositioned.
- **(C)** FAIL at both, and CRITICAL is never dispositionable (fix-only).

**Recommended: (B).** It preserves exactly what the old gate's ESCALATE did, which was disclosure
before authorization (F10), and places that disclosure where the human decides. It also avoids a
FAIL-every-release disposition ritual that would train rubber-stamping. CRITICAL keeps a hard
stop. Cost: a third suite state in R2/R3/R4, which is a protected `worker.md` edit. **Revisit
after #1623 S0:** if the measured full-run composite is MEDIUM, (A) becomes affordable.

**ESC-2 — Does `tier_floor` count toward REQ-B2?** The options:
- **(A)** composite only, with floors informational;
- **(B)** composite plus every floor except `diff_size`;
- **(C)** composite plus all floors.

**Recommended: (A).** It is REQ-B2's literal "composite tier" and the old check 3's actual
behaviour (F2: `step1754` was not flagged). (C) makes every release HIGH by construction, because
456 files is more than the 15-file floor (F5), so the gate would carry no information. The
non-size floors (bandit HIGH, semgrep ERROR) are defects that REQ-B3 already catches as findings
under ESC-3 (B), so (B) here would double-count.

**ESC-3 — Which findings are "CRITICAL/HIGH validator findings" (REQ-B3)?** The options:
- **(A)** every `high`/`critical` item in any dimension's `evidence` or `findings`. That is about
  46 or more items per release, mostly whole-file complexity, RN and shell-density metrics on
  pre-existing code, and it is a truncated sample (F7).
- **(B)** defect-class dimensions only: `static_analysis` (bandit HIGH), `static_analysis_js`
  (semgrep ERROR), `ip_check` (high, i.e. copyleft), `migration_risk` (CRITICAL/HIGH ops) and
  `portability` (high). The metric dimensions (`risk_number`, `complexity`, `function_metrics`,
  `shell_logic`, `hallucination`) feed REQ-B2's composite and do not block as findings.
  `historical_density` (past labelled issues, not a current defect) is excluded too.
- **(C)** only findings new in the range relative to the base tag. That needs a second baseline
  run at the tag, which is expensive and new machinery.

**Recommended: (B)**, held as a named constant. It is a formal narrowing of REQ-B3's literal text,
but not of anything ever enforced, because the old check 4 could not fire (F2). Record it as a
REQ-B0(ii) decision under ESC-8. Sub-question for the human: should `portability` and
`historical_density` be in or out?

**ESC-4 — Disposition pinning.** Should a disposition be honoured only for the candidate head SHA
it names, or carry to a later candidate on the same issue when the finding identifier is
unchanged? **Recommended: head-pinned.** This matches R5 condition 10, #1623 ESC-3 and the
architect's ADR-1623 recommendation. Cost: a fix commit on the candidate requires the
dispositions to be re-posted. One comment can list many items.

**ESC-5 — Bulk disposition?** For example `finding:shell_logic:*`. **Recommended: no.** Items are
itemised only, consistent with ADR-1624 R8.2/AD-7. Revisit only if ESC-3 = (A).

**ESC-6 — Findings beyond a validator's cap (REQ-T7).** The excess cannot be named individually.
The options:
- **(A)** a count-bound item, `finding:<runner>:unitemised=<k>`, that the human can disposition
  only at that exact count and head;
- **(B)** require uncapped output in release mode. That is a change to `validators/` and the
  runner, and #1623 or a new issue owns it.
- **(C)** treat it as INDETERMINATE until fixed.

**Recommended: (A)** for v1, with (B) as a follow-up.

**ESC-7 — Tier and findings over a coverage-dispositioned run.** Suppose #1623 coverage is
DEGRADED and the human dispositions the missing dimensions under #1623 ESC-3. The tier is then
computed over fewer dimensions and understates risk (F4). **Recommended:** evaluate it, but print
`computed over <k>/<n>; not scored: …` on line 1, and never emit plain PASS. Emit
`PASS-DISCLOSED` (or FAIL under ESC-1 (A)). The alternative is INDETERMINATE whenever coverage is
not a clean PASS.

**ESC-8 — The granularity reduction and the open window.**
(a) G-b and G-c move from per-step artifacts to one aggregate verdict over the release range.
(b) G-b and G-c are effectively unchecked today, and G-c never was (F2).

**Recommended: accept both.** Record them in the same DECISIONS.md entry as #1623 ESC-1 and #1624
ESC-1, as REQ-B0(ii) human-approved reductions, together with ESC-3's narrowing. No interim check.

## 7. Escalation flag (CORE self-flag)

RISK: HIGH. This is a release gate at every tier. A gate that passes wrongly manufactures
confidence. One that fails every release by construction (F5, F6) trains people to route around
it. It edits a protected surface (the `worker.md` R2/R3/R4 rows), and it reads a protected
threshold source.

CONFIDENCE: 75%.
- **High** on F1–F5 and F7–F10: code read and git state inspected this session, including the two
  committed artifacts.
- **Medium** on F6: a 7-of-13 partial run, with no network dimensions and no ScanCode.
- **Verification gap:** whether the full release composite is HIGH is unmeasured until #1623 S0.
  ESC-1's recommendation is explicitly conditional on that measurement.

BLAST RADIUS:
- whether any release can be cut;
- the human's per-release disposition workload (ESC-1, ESC-3);
- a new suite state in R2/R3/R4.

There is no per-PR effect (REQ-T12). The work depends on #1623 S1+S2 (its run) and on #1624 S3
(the disposition reader).

Classification: **structural**. It adds a release-blocking condition at every tier (REQ-T4,
REQ-T5, REQ-T11). It adds a human disposition step (REQ-T9) and possibly a new suite state
(ESC-1 (B)). It formally narrows REQ-B3 and the granularity of G-b and G-c (ESC-3, ESC-8). None of
this may be written into `worker.md`, `overseer.md` or the contract without human sign-off. This
document proposes these changes; it does not authorize them.

## Human Review Required

- **ESC-1..ESC-8.**
  - ESC-1, ESC-2 and ESC-3 must be answered before technical design. They determine whether the
    gate carries information at all.
  - ESC-4..ESC-8 have safe defaults. Design may assume them, but they are not binding until the
    human confirms them.
- **`.claude/agents/worker.md` R2 (and R3/R4 under ESC-1 (B))** is a protected-surface edit, and
  goes through CODEOWNERS.
- **F2 contradicts the issue's premise.** The issue says the replacement "does not currently
  enforce" G-b/G-c, which implies the old gate did. In fact the old check 4 (G-c) could never fire,
  because of field-name and case mismatches, and check 3 (G-b) evaluated at most two stale
  artifacts.
- **F5 and F6 mean REQ-B2 as literally written** (any HIGH, floors included, FAIL) **would block
  every release.** ESC-1 and ESC-2 decide whether that is intended.
