# ADR-1622 — Release-range tier and finding gate (REQ-B2/B3, re-homing G-b and G-c)

Issue: #1622 (milestone v0.7.0). Parent: #1340. Siblings: #1623 (REQ-B4), #1624 (REQ-B5), #1625 (REQ-A13).
Author: architect. Date: 2026-10-14. Baseline: `943d03228` (branch; `origin/main` = `8845e8e09`, an ancestor).
Input: `docs/v0.7.0/REQUIREMENTS-1622-release-range-tier-finding-gate.md` (pm-agent, REQ-T1..T14, ESC-1..8).
Coordinates with: `ADR-1623-release-range-validator-coverage.md` (AD-2, AD-3, AD-5, AD-6, S3, FU-5), `ADR-1624-release-range-review-evidence.md` (AD-4, AD-6, AD-7, ARCH-ESC-3), `ADR-1340-release-panel.md` (AD-9), `.claude/agents/worker.md` NG3b R1.9–R5, `.claude/agents/overseer.md` "Release-gate deep validation (#695)".

**Verdict on the requirements: APPROVED_WITH_AMENDMENTS.** The product framing is right:
- consume #1623's one release-range run, and never start a second;
- derive the tier from the one named threshold source, and fail closed on drift;
- block on undispositioned defect-class findings, and leave a dispositioned finding visible;
- one disposition surface, identity-bound and head-pinned;
- per-PR behaviour unchanged.

Nine amendments (AM-1..AM-9, §10) correct six premises. Four of them would have produced a gate that passes wrongly or can never pass:
- the named comment transport `query_issues.sh --comments-json` cannot satisfy REQ-T9 (AF-1);
- R4 never shows a passing suite's line 1, so "PASS-DISCLOSED" as specified discloses nothing (AF-2);
- finding identifiers that are not stable across two runs at the same head make every disposition self-defeating, because the disposition comment itself forces a fresh run (AF-3);
- a persisted `validators-release/` tree is only evidence for the current candidate if it is sealed and re-verified, and a sealing record named `*.json` would poison the aggregator (AF-4).

**Status: Accepted (technical).** ESC-1..8 stay with the human (§11). ARCH-ESC-1..3 are added. S0, S1 and S2 can proceed before any human answer (§9).

---

## 0. Verification of the pm-agent's claims (re-derived at `943d03228`)

| # | Claim | Verdict | Evidence read this session |
|---|---|---|---|
| 1 | F1: `run_validators.sh` exits 0 at every tier; R2/R3 see only the exit code | **Stands** | The aggregator's only `sys.exit(1)` is the all-failed path (`run_validators.sh:483`). The R2 table has no argument column (`worker.md:647-653`, not `:645-651`). R3's format is `PASS\|FAIL (exit <code>)` plus a first-line excerpt on FAIL (`:663-666`). |
| 2 | F2: check 3 reads `tier`, not `tier_floor`; `step1754` is `tier=MEDIUM`, `tier_floor=HIGH` | **Stands** | `overseer.md:193`. `git show origin/main:signoffs/validators/step1754/summary.json` → tier MEDIUM, floor HIGH, composite 0.4009. `step1` → LOW, 0.1551. Only these two artifacts exist on `origin/main`. |
| 3 | F2: check 4 can never fire | **Stands, on all three grounds** | Check 4 reads `results[].findings` (`overseer.md:194`). Only `rn_calculator.py:322` and `rn_calculator_js.py:381` populate `findings`, and those entries have no `severity` key (21 and 46 entries in the two artifacts, all `None`). Every other validator puts located items in `evidence` via `make_finding` (`schema.py:13`), with lowercase severities. No validator emits `critical`: `migration_scorer.py:116` maps CRITICAL → `"high"`, and `ip_check.py:457` coerces any non-`high/medium/low` severity to `"low"`. |
| 4 | F3: `TIER_THRESHOLDS` is read by no code path | **Stands** | `grep` over `scripts/ bootstrap/ bin/ tests/`: only comments reference it (`require_tier_ceiling.py:144`, `gate_compliance.py:24,33`). |
| 5 | F3: "five hard-coded copies" | **Corrected: at least six code sites, plus agent prose.** | `schema.TIER_THRESHOLDS` (`:84-89`); `schema.score_to_tier` (`:105-114`), which **is** used in production by `rn_calculator.py:373` and `rn_calculator_js.py:423`; `run_validators.sh:487` `TIERS`; `require_tier_ceiling._score_to_tier` (`:140-154`); `gate_compliance._CRITICAL_THRESHOLD` (`:34`, CRITICAL only); and `run_second_review.sh:71-72`, whose `OVERSIGHT_AGY_THRESHOLD=0.30` / `OVERSIGHT_CODEX_THRESHOLD=0.55` defaults are documented as "MEDIUM+" / "HIGH+". `risk-assessor.md` and `oversight-evaluator.md` also quote the boundaries. This does not change the design (REQ-T14 still consolidates nothing); it widens FU-1's scope. |
| 6 | F3: a naive `lo ≤ score < hi` maps 1.0 to no tier | **Stands** | `TIER_THRESHOLDS["CRITICAL"] = (0.78, 1.00)` with the `:80` comment "hi exclusive". AD-3 uses the lower bound only. |
| 7 | F4: errored validators drop out of numerator and denominator | **Stands** | `run_validators.sh:458-464`, `schema.composite_score:92-102`. Both use truthiness of `error`, so `error: ""` is **included** in the composite while ADR-1623 AD-2 classifies it as `errored`. AD-3 handles this divergence. |
| 8 | F5: `diff_size` floors any release-sized set to HIGH | **Stands** | `diff_size.py:42-43` (400 lines / 15 files, strict `>`), `:160-166`. |
| 9 | F7: caps and counts per dimension | **Partly corrected.** | Confirmed: top-5 caps in `rn_calculator.py:295`, `complexity_metrics.py:131` and their JS twins; bandit HIGH `[:10]` with `bandit_high_count` (`static_analysis.py:157,196`); `migration_scorer` evidence uncapped, with `critical_count` and `high_count` (`:116`, `:172-173`). **Corrections:** (a) `ip_check`'s `raw_value` carries the **full, uncapped** `dependency_findings` and `prompt_findings` lists (`ip_check.py:490-493`), so its high items are exactly itemisable and need no excess count. (b) `issue_query` does carry a count, `raw_value.issue_count` (`:218`), but it counts all matched issues, not the high-severity ones, so its high-item total is still unknowable. (c) `static_analysis_js` caps semgrep ERROR at `[:10]` (`:127`) and carries `semgrep_error_count` (`:149`); pm did not list this pair. (d) `portability` is uncapped and carries `finding_count` (`portability_check.py:88-110`). |
| 10 | F9 / REQ-T9.2: `query_issues.sh --comments-json` is an admissible structured transport | **Wrong. See AF-1.** | `bootstrap/query_issues.sh:295-297`: one `gh api …/comments?per_page=100` call with no `--paginate` and no page loop. It emits only `user` (login), `created_at` and `body`, with no `id`, `user.type` or `updated_at`. It silently truncates past 100 comments, and it cannot express REQ-T9.1 (`user.type`) or REQ-T9.3 (unedited). `github.list_issue_comments` (`github.py:215-238`) has ADR-1624 AF-3's later-page-404 truncation defect. Neither may be used. |
| 11 | F10: every release already reaches a human via R4 | **Stands, and it is worse than stated. See AF-2.** | R4 item 1 records "suite name, exit code, UTC timestamp" only (`worker.md:712-713`). No passing suite's line 1 ever reaches the human. |
| 12 | F6: the release composite is likely HIGH | **Not re-measured here.** I accept it as a partial measurement. Note that pm's 7-dimension partial composite was 0.76, which is 0.02 below CRITICAL. CRITICAL on the full run is a live possibility, not a tail case (ARCH-ESC-1). | — |

**Searched for reuse (CLAUDE.md item 1).** I searched `scripts/`, `bootstrap/`, `bin/` and `scripts/automation/lib/`.
- Found and reused: `schema.TIER_THRESHOLDS`, `schema.score_to_tier`, `schema.composite_score` (importing `scripts.oversight.validators.schema` has no `sys.path` side effect; `validators/__init__.py` is empty, verified); `release_panel_logic.run_git`; ADR-1623's `classify` and content-pin preconditions; ADR-1624's AD-7 reader and AD-4 `fetch_raw_pages`; `review_state.resolve_machine_accounts`; `require_human_approval.is_bot_reviewer`.
- Not yet built: every one of ADR-1623 S1/S2/S3 and ADR-1624 S0..S3 (`ls scripts/oversight/release_*` shows only `release_artifact_logic.py`, `release_logic.py`, `release_panel_logic.py` and the exclusions file). So this ADR orphans no code.
- No existing tier-gate or finding-sweep code exists anywhere.

### Architect's findings (these change the design)

**AF-1 (HIGH): the named transport cannot carry a disposition.** See row 10. A disposition read through `--comments-json` would:
- silently lose every comment past the 100th (a release-request issue accumulates R3 comments across cycles);
- be unable to apply the `user.type == "User"` test;
- be unable to apply ADR-1624's unedited rule, so a human comment that a bot later edited would be honoured.

The only admissible reader is ADR-1624 AD-7's: comments fetched by `github.fetch_raw_pages` and assembled by `review_state`'s completeness rule (ADR-1624 AD-4, E-1624-1). AM-1 strikes `--comments-json` from REQ-T9.2.

**AF-2 (HIGH): disclosure at R4 does not exist today for any passing suite.** R4 records exit codes and timestamps, not output. The consequences:
- pm's ESC-1 (B) PASS-DISCLOSED cannot reach the human through a distinct exit code alone. R2/R3 treat every non-zero exit as FAIL, and R4 never quotes a passing suite.
- ADR-1623 AD-5's statement "a PASS line still lists any not-scored names, so a PASS with tolerated losses is visible" is **false at the decision point** for the same reason. A tolerated 11/13 coverage PASS never reaches the human.

AD-8 and AD-9 fix both with one R4 change: on all-pass, R4 quotes **every required suite's line 1 verbatim**. PASS-DISCLOSED is then exit 0 with a distinct line-1 outcome token. That re-opens one ADR-1623 claim (§12).

**AF-3 (HIGH): unstable identifiers make dispositions self-defeating.** A disposition comment is a non-`BOT_ACCOUNTS` comment, so R1.9 check 3 forces a **fresh** release-range run at the same head (`worker.md:610-614`).
- If any blocking item's identifier differs between two runs at the same head, the fresh run prints a new identifier, the disposition no longer matches, and the release can never pass.
- Sources of instability: list order (bandit and ScanCode output order is not contractually sorted), and live-state dimensions. `historical_density` reads GitHub issues and git churn as of *now*, so its evidence changes with no code change.

AD-5 makes identifiers content-derived and order-independent. AD-4 keeps live-state dimensions out of the blocking set unless the human rules otherwise. S4's demonstration run must show two runs at one head yielding identical identifier sets.

**AF-4 (HIGH): a persisted run is evidence only if sealed, and the seal must not be a `*.json` file.** The tier suite is a separate R2 row (AD-1). It reads a `validators-release/` tree that #1623's checker left behind. That tree could be:
- from an earlier head;
- from a run killed part-way through;
- from a run whose coverage suite was a carry-forward skip this cycle (R1.9 check 3).

So the run needs a seal: ranges, hashes and the coverage outcome, written last (AD-2). The seal must **not** be named `*.json`. The aggregator globs `OUT/*.json` and excludes only `summary.json` and `gate-results.json` (`run_validators.sh:442-454`). Any other dict-shaped JSON there is included in the composite with `score` 0.0 and `weight` 1.0, which silently **lowers** the tier. The seal is therefore `OUT/run-record.tsv`.

**AF-5 (MEDIUM): two composite definitions diverge on `error: ""`.** The aggregator and `schema.composite_score` include a result with a falsy non-`None` error. ADR-1623's coverage table counts it as `errored`. The composite the gate tiers on is the aggregator's, so AD-3 recomputes it with the aggregator's exact rule (via `schema.composite_score`, in filename order) and requires exact equality with `summary.composite_score`. AD-3 does not "correct" the rule: that would make the release tier disagree with every per-PR tier for the same files.

**AF-6 (MEDIUM): ADR-1623's wrapper "takes no arguments", but its S3 override needs the release-request issue number.** The S3 override reads comments on the release-request issue (ADR-1623 S3), and the issue number is not derivable from git. This does not block #1622, because this gate applies #1623's override itself (AD-2 step 4) from the comments it already reads. It is recorded as a coordination note for #1623 S3 (§12).

**AF-7 (LOW): a blocking runner that did not score hides its findings.** ESC-7's recommendation evaluates the tier over a coverage-dispositioned degraded run. But if the missing runner is in the blocking set (for example `static_analysis` timed out), its finding count is *unknown*, not zero. The human's coverage disposition accepted a missing *score*. It did not accept *unknown defects*. AD-4 emits a separate blocking item for that case.

**AF-8 (LOW): exit-code collision.** This is the same defect as ADR-1623 AF-8 and ADR-1624 AF-8, with the same cure (AD-8).

---

## 1. Where the gate lives

### AD-1: a new Python module behind a thin `.sh`, as its own R2 row. It reads #1623's sealed run and never produces one.

- **`scripts/oversight/release_tier_findings.py`** holds all decisions in three layers:
  - **Pure core:** `evaluate(run: SealedRun, coverage: CoverageResult, dispositions: DispositionSet, candidate_head: str) -> TierFindingResult` and `render(result) -> (lines, exit_code)`. No I/O.
  - **Collector:** `load_sealed_run(out_dir)`, `verify_binding(...)` (AD-2), and the disposition read through the shared reader (AD-7).
  - **CLI:** `main(argv)`.
- **`scripts/oversight/release_tier_findings.sh`** is the R2 path. It is thin, as in ADR-1623 AD-1 and ADR-1624 AD-1: resolve `REPO_ROOT`, `exec python3 -m scripts.oversight.release_tier_findings "$@"`, and map any exit code outside {0,1,2} to 2. It contains no logic (SPEC-333).
  - Fixed invocation: `bash scripts/oversight/release_tier_findings.sh --issue <release-request issue #>`.
  - `--issue` is constant for one release request, so R1.9 check 3's per-path anchor walk stays unambiguous.
- **What it never does** (REQ-T1, AC-14):
  - invoke `run_validators.sh`;
  - call `derive_range`;
  - write any file. It writes nothing at all: no stamp, no cache, no register (REQ-T9.6). Diagnostics go to stderr.
  - A static test asserts that the module has no `subprocess` site other than `release_panel_logic.run_git` and the `github` read surface.
- **Rejected: folding the verdict into `release_validator_coverage.py`** (REQ-T11 left this to the architect). Reasons:
  1. It merges two exit lattices (coverage DEGRADED vs tier/finding FAIL) into one exit code, and two line-1 grammars into one line.
  2. It re-opens ADR-1623's approved AD-5 and AD-6 output contract.
  3. It couples #1623's arming to #1622's ESC-1/2/3, which are the hardest open questions in the #1340 split. #1623 can arm without them.
  4. It needs `--issue`, which ADR-1623 AD-1 deliberately omits.

  The cost of a separate row is that the single-run binding must be *checked*. AD-2 does that, and it is cheap.
- **Rejected: a tier exit in `run_validators.sh`.** It is protected, its per-PR exit contract is frozen (REQ-T12), and it would put judgment into a producer (SPEC-333).

## 2. Binding to one complete run

### AD-2: #1623's checker writes a seal last. This gate verifies the seal, re-derives coverage from the same files, and pins it to the candidate head.

**E-1622-2 (an addition to ADR-1623 S2; binding on whoever codes it).** After classification, and on every terminal path that reached the runner (including DEGRADED and budget-exhausted), `release_validator_coverage.py` writes `OUT/run-record.tsv` atomically (tmp file + `os.replace`) as its **last** filesystem act. It is never named `*.json` (AF-4). Its fields are `key<TAB>value` lines:

```
schema	1
base_ref	v0.6.0
base_sha	<40-hex>
head_sha	<40-hex>
finished_at	<UTC ISO-8601>
runner_exit	<int>
coverage_outcome	PASS|DEGRADED|INDETERMINATE
sha256	files.txt	<hex>
sha256	dispatch.tsv	<hex>
sha256	summary.json	<hex>
sha256	<name>.json	<hex>          # one line per dispatched name whose outfile exists
```

It also exports, as public pure functions, `classify(manifest, outfiles, range) -> CoverageResult` (already in ADR-1623 AD-1) and `check_content_pin(head_sha) -> None | Refusal` (AD-3 step 2, factored out). When S3 exists, it also exports `apply_overrides(result, dispositions) -> CoverageResult`.
- None of this changes the runner, the coverage verdict or `summary.json`. It is inside REQ-T1's allowance ("added in #1623's … release mode").
- **If #1623 S2 is not yet coded, its coder includes E-1622-2. Otherwise this issue's S1 adds it.**

**This gate, in order.** The first failure ends the run as INDETERMINATE (exit 2) with a cause token. No tier or finding list is printed.
1. **Seal present and well-formed.** `OUT = .claudetmp/oversight/validators-release/`. Missing, malformed, a duplicate key or an unknown `schema` → `run-unsealed`.
2. **Hashes.** Every file named in the seal is re-hashed and must match. Every dispatched name in `dispatch.tsv` whose outfile exists must have a seal line. A mismatch → `run-record-mismatch:<file>`. This rules out a partial overwrite, a stray file, or a run killed after the seal of an earlier run.
3. **Candidate binding.** `rpl.run_git(["rev-parse","HEAD"])` must equal `head_sha` → else `head-moved`. `check_content_pin(head_sha)` must pass → else `dirty-tree`. `finished_at` must be no more than `MAX_RUN_AGE_S = 3600` before now, and not in the future → else `run-stale`. The age bound stops a run from a previous cycle at the same head being reused after the live-state dimensions (`historical_density`, `ip_check`) have moved.
4. **Coverage, re-derived and not trusted.** `cov = release_validator_coverage.classify(...)` over the same `OUT/` files, then `apply_overrides(cov, dispositions)` once #1623 S3 exists. `cov.outcome` must equal the seal's `coverage_outcome` (pre-override) → else `coverage-record-mismatch`.
   - `cov` PASS → continue.
   - `cov` DEGRADED and human-overridden under #1623 ESC-3 → continue under ESC-7's policy (AD-6).
   - Anything else → INDETERMINATE `coverage-<outcome>` (REQ-T6, AC-7).
5. **Summary shape.** `summary.json` is a dict. `composite_score` is a non-bool finite number in [0, 1]. `tier` is one of the four tier keys. `results` is a list. Otherwise → `summary-unparseable`.

**Why re-classify rather than read `coverage_outcome`.** The seal records what #1623 decided. Re-running its pure `classify` on the hashed files proves that the decision belongs to *these* files. This is ADR-1340 AD-7's "recompute what you can, trust only what you cannot" applied across suites, and it costs microseconds.

**Interaction with R1.9 check 3 (REQ-T11).**
- If the coverage row is a carry-forward FAIL this cycle, `OUT/` is that failed run, so this gate reports INDETERMINATE `coverage-DEGRADED`/`coverage-INDETERMINATE` and fails as well. That is consistent.
- If this row is carried forward and coverage re-runs, the restated FAIL stands until a human comment or the 6 h backoff forces a fresh run. FAIL is never turned into PASS by carry-forward.
- The coverage row **must run before** this row in the same cycle. AD-9 makes R2's table order normative. If the order is violated, step 3's age bound or step 2's hashes fail closed; the result is never a stale PASS.

## 3. Tier

### AD-3: the tier comes from `TIER_THRESHOLDS` by lower bound. Drift between the copies is detected at runtime. The composite is re-derived from the per-runner outfiles.

- **Derivation.** `derive_tier(score) = max(t for t, (lo, _hi) in TIER_THRESHOLDS.items() if lo <= score)`, ordered by `lo`. `hi` is never read. So 1.0 → CRITICAL, 0.78 → CRITICAL, 0.55 → HIGH, 0.30 → MEDIUM, 0.2999 → LOW (AC-1). The module contains no tier boundary literal. A static test greps the module for `0.30`, `0.55`, `0.78` and `0.3\b`.
- **Runtime parity check (REQ-T2).** At evaluation time the gate asserts, for every tier `t` with lower bound `lo`, that `schema.score_to_tier(lo) == t`, and for `lo > 0`, that `score_to_tier(math.nextafter(lo, 0)) == ` the previous tier. A violation → INDETERMINATE `threshold-copy-drift:schema`. It then asserts `summary.tier == derive_tier(summary.composite_score)` → else `threshold-copy-drift:aggregator`. The aggregator's `TIERS` copy is covered here, because it is what wrote `summary.tier`. No protected file is edited.
- **Composite re-derivation (AF-5).** `recomputed = schema.composite_score(results)`, where `results` are the dict-shaped per-runner outfiles of every dispatched name, iterated in **sorted filename order** (the aggregator's `sorted(out_dir.glob(...))` order, so float summation order matches). It requires `recomputed == summary.composite_score` exactly (both are `round(…, 4)`) → else `composite-mismatch`.
  - A result lacking `score` raises `KeyError` in `schema.composite_score`. That is caught and reported as `result-unparseable:<name>` (INDETERMINATE).
  - The aggregator's fail-closed composite of 1.0 is only produced on the all-failed path, which coverage step 4 already rejects.
- **Floors (REQ-T3, ESC-2).** Floors are read **per runner name** from the outfiles, never from `summary.tier_floor` (a max with no attribution) or from `dimension` (ADR-1623 AF-2).
  - Each runner's `tier_floor` must be `None` or one of the four tier keys → else `result-unparseable:<name>`.
  - `GATING_FLOOR_RUNNERS: frozenset[str]`. Interim `frozenset()` = ESC-2 (A). Option (B) = every floor-emitting runner except `diff_size` (today `static_analysis`, `static_analysis_js`, `risk_number`, `risk_number_js`). Option (C) adds `diff_size`.
  - `gated_tier = max(derive_tier(composite), floors of GATING_FLOOR_RUNNERS)`. All floors are shown on line 1 regardless.
- **Weights are taken as the aggregator takes them.** That is self-reported per result (`r.get("weight")`), not `schema.WEIGHTS`. Correcting that is a per-PR change, out of scope here (FU-3).

## 4. Findings

### AD-4: findings are extracted per runner name by a closed adapter table. Severity is normalised, completeness is checked against counts, and a blocking runner that did not score is itself a blocking item.

- **`BLOCKING_RUNNERS: frozenset[str]`** (ESC-3), keyed by **runner name** (AM-2). Interim, pm's option (B): `{"static_analysis", "static_analysis_js", "ip_check", "migration_risk", "portability"}`. The JS twin `static_analysis_js` emits `dimension = "static_analysis"`, so dimension-keying would merge the two lanes (ADR-1623 AF-2).
- **`ADAPTERS: Mapping[str, Adapter]`**, one per runner that may be blocking. An adapter maps the runner's result dict to `(items, unitemised_k)` and validates the shape it reads. A shape violation → INDETERMINATE `result-unparseable:<runner>`. An import-time assertion requires `BLOCKING_RUNNERS ⊆ ADAPTERS.keys()`, so a ruling cannot add a runner without an audited adapter. The per-runner completeness record (REQ-T7, verified this session):

  | Runner | Item source | Cap | Count field | Completeness rule |
  |---|---|---|---|---|
  | `static_analysis` | `evidence` severity `high` (bandit HIGH) | `[:10]` (`:157`) | `raw_value.bandit_high_count` | `k = count − itemised`; `k < 0` → INDETERMINATE |
  | `static_analysis_js` | `evidence` severity `high` (semgrep ERROR) | `[:10]` (`:127`) | `raw_value.semgrep_error_count` | as above |
  | `ip_check` | `raw_value.dependency_findings` + `raw_value.prompt_findings` with severity `high` (copyleft) — **not** `evidence` | none | `raw_value.high_count` | exact: itemised must equal `high_count`, else INDETERMINATE |
  | `migration_risk` | `evidence` severity `high` (CRITICAL and HIGH ops) | none | `critical_count + high_count` | exact |
  | `portability` | `evidence` (all `high`) | none | `raw_value.finding_count` | exact |
  | `historical_density` (only if ESC-3 includes it) | `evidence` severity `high` | `[:10]` issues | `issue_count` counts **all** issues | high total unknowable → `k` is reported as an upper bound `unitemised<=k`, never as exact |
  | metric runners (only under ESC-3 (A)) | `evidence` severity `high` | `[:5]` | `raw_value.high_risk_functions` (RN, uncapped list) / `high_complexity_functions` (complexity, count) | technical-design verifies each runner and its JS twin before (A) can be armed |

- **Severity.** It must be a `str`. `strip().lower()` must be in `KNOWN_SEVERITIES = {"info","low","medium","high","critical"}`, else INDETERMINATE (`result-unparseable`). An item blocks iff its severity is in `BLOCKING_SEVERITIES = {"high","critical"}` (AC-4). `findings` entries are read only by an adapter that names them. `rn`'s `findings` have no severity and are never blocking (AC-4's third case).
- **Unitemised excess (REQ-T7, ESC-6).** `k > 0` produces one blocking item, `finding:<runner>:unitemised=<k>`. Interim `UNITEMISED_POLICY = "item"` = ESC-6 (A). `"indeterminate"` = (C).
- **Not-scored blocking runner (AF-7).** If a runner in `BLOCKING_RUNNERS ∩ dispatched` is not scored (any non-`scored` class in ADR-1623's table), it produces the blocking item `finding:<runner>:not-scored`. Its findings are unknown, and that is never read as zero. A coverage override for that runner does **not** clear this item. It needs its own disposition.
- **Non-blocking items.** High items from runners outside `BLOCKING_RUNNERS` are counted per runner on a later output line as informational (AC-5). They never affect the verdict.

## 5. Identifiers

### AD-5: identifiers are content-derived, order-independent, and stable across re-runs at the same head (AF-3)

- **Form:** `finding:<runner>:<h12>`, where `h12` is the first 12 hex characters of `sha256` over a canonical JSON array:
  - for evidence items: `[runner, file, line, severity_lower, message]`;
  - for `ip_check` raw findings: `[runner, file, package, spec, license, category]`.
- **Duplicates.** Items with identical canonical tuples are disambiguated by sorting the tuples and suffixing the 2nd and later as `.2`, `.3`, …. That makes the suffix independent of validator output order.
- **Never** derived from `dimension`, and never from message text alone (REQ-T9). The message is one field of a tuple anchored on runner, file and line.
- **Line 1 safety.** The identifier is `[a-z_]+:[0-9a-f]{12}(\.[0-9]+)?`, so no attacker-influenced byte reaches line 1 (REQ-T10).
- **Stability is a binding requirement, not a hope.**
  - Unit test: the same fixture with its evidence list shuffled → identical identifier set.
  - S4 precondition: two demonstration runs at one head → identical blocking identifier sets.
  - `historical_density` is excluded from the interim blocking set partly because its evidence is live-state (ESC-3 note).
- **Cross-head stability is not required.** Under ESC-4 (head-pinned), a new head needs fresh dispositions anyway. If the human rules ESC-4 = carry, this AD must be revisited, because line numbers are part of the tuple.

## 6. Verdict

### AD-6: one verdict lattice. Every human-relevant ruling is an isolated constant.

**Constants (interim = pm's recommended defaults; each ruling is a constant flip plus its tests):**

| Constant | Interim | ESC |
|---|---|---|
| `TIER_POLICY = {"LOW":"pass","MEDIUM":"pass","HIGH":"disclose","CRITICAL":"block"}` | (B) | ESC-1. (A) sets HIGH → `"block"`. (C) sets CRITICAL → `"block-final"` (not dispositionable). |
| `GATING_FLOOR_RUNNERS = frozenset()` | (A) | ESC-2 |
| `BLOCKING_RUNNERS` | (B) set, AD-4 | ESC-3 |
| `HEAD_PINNED = True` | pinned | ESC-4 (no other value is implemented in v1) |
| `UNITEMISED_POLICY = "item"` | (A) | ESC-6 |
| `DEGRADED_COVERAGE_POLICY = "disclose"` | pm's recommendation | ESC-7. `"indeterminate"` is the alternative. |
| `DISPOSITION_SOURCE = "none"` | no dispositions | wired in S3 |

**Evaluation** (pure; first matching row wins):
1. Any AD-2 or AD-3 failure → **INDETERMINATE** (exit 2).
2. `blocking_undispositioned` = the blocking items of AD-4, plus `tier:<T>` if `TIER_POLICY[gated_tier]` ∈ {block, block-final}, minus validly dispositioned items (AD-7). A `block-final` tier item is never removable.
3. Non-empty → **FAIL** (exit 1).
4. Otherwise **PASS-DISCLOSED** (exit 0) if any of:
   - `TIER_POLICY[gated_tier] == "disclose"`;
   - any item was dispositioned;
   - coverage reached step 4 through a human override (ESC-7, AF-7);
   - the composite was computed over fewer than all dispatched runners (`computed over <k>/<n>`).
5. Otherwise **PASS** (exit 0). This is only possible when the tier is LOW or MEDIUM, nothing is dispositioned, and coverage is a clean PASS with every dispatched runner scored.

So a HIGH or CRITICAL release, or a release with any dispositioned item, can never produce plain PASS (REQ-T4, REQ-T5).

## 7. Dispositions

### AD-7: one shared reader, a namespaced grammar, and head pins

**Reader: exactly one in the system (REQ-T9, REQ-T14).** It is ADR-1624 AD-7's reader:
- `fetch_raw_pages` on `…/issues/{n}/comments`, assembled by the E-1624-1 completeness rule;
- author = `HUMAN_REVIEWER` (case-insensitive) and `user.type == "User"` and not `is_bot_reviewer`;
- unedited (`updated_at == created_at`);
- page cap, `Unknown` or a malformed item → INDETERMINATE.

`--comments`, `--comments-json` and `list_issue_comments` are never called (AF-1). A static test asserts all three strings are absent from the module (AC-10).

**E-1622-1 (binding on whichever of #1624 S3, #1623 S3 or #1622 S3 is coded first).** The reader is built **once**, in a shared module `scripts/oversight/release_dispositions.py`. It is not built inside `release_review_evidence.py`, because three gates import it. It returns `ParsedDisposition(url, author, created_at, items: tuple[str, ...], head_pin: str | None, reason)` for each honoured line, plus `ignored: tuple[(url, cause)]`. The ADR-1624 AD-7 grammar is extended **additively**:

```
^Disposition:\s+(?P<items>ITEM(\s*,\s*ITEM)*)(\s+@(?P<head>[0-9a-f]{40}))?\s+(—|--)\s+(?P<reason>\S.*)$
ITEM := #<digits> | <40-hex> | validator:<runner> | tier:(HIGH|CRITICAL)
      | finding:<runner>:(<12-hex>(\.\d+)? | unitemised=<digits> | not-scored)
<runner> := [a-z][a-z0-9_]*
```

- ADR-1624's own items (`#n`, 40-hex SHA) behave exactly as AD-7 specifies. The optional `@<head>` is ignored for them unless #1624 rules otherwise.
- Wildcards, `all`, short SHAs, short heads and an empty reason do not match, so the line is ignored as `DISPOSITION_IGNORED_MALFORMED` (AC-9, ESC-5).

**This gate's matching rules.**
- Only `tier:` and `finding:` items are considered. `validator:` items go to #1623's `apply_overrides`.
- A `tier:` or `finding:` item is honoured only if `head_pin` is present **and** equals the candidate head (ESC-4, AC-9). A missing or different pin → listed as `DISPOSITION_IGNORED_UNPINNED <url>` / `DISPOSITION_IGNORED_OTHER_HEAD <url>`.
- `tier:<T>` is honoured only when `T == gated_tier`. `finding:<runner>:unitemised=<k>` is honoured only at exactly that `k`.
- An honoured item becomes DISPOSITIONED with its URL. It stays on output lines 2+ and is counted on line 1 (REQ-T5, REQ-T8).

**Interim.** `DISPOSITION_SOURCE = "none"` until S3, so every blocking item blocks. That is fail-safe and inert until arming.

## 8. Output and exit contract

### AD-8: line 1 carries everything R3 and R4 quote. Exit codes are disjoint and crash-safe (mirrors ADR-1623 AD-5 and ADR-1624 AD-6).

**Line 1** is a single line made of tokens, identifiers, counts and SHAs only. It contains no path and no message (REQ-T10, AC-11).
```
RELEASE-TIER-FINDINGS PASS — tier MEDIUM (composite 0.4210; floors diff_size=HIGH) — blocking 0 — coverage PASS 13/13 — range v0.6.0@<sha12>..<sha12>
RELEASE-TIER-FINDINGS PASS-DISCLOSED — tier HIGH (composite 0.6120; floors diff_size=HIGH, static_analysis=HIGH) — blocking 0 undispositioned, 1 dispositioned: finding:static_analysis:3f9a1c2b7e4d — coverage PASS 13/13 — range v0.6.0@<sha12>..<sha12>
RELEASE-TIER-FINDINGS FAIL — tier CRITICAL (composite 0.8123; floors diff_size=HIGH) — blocking 3 undispositioned: finding:ip_check:9c01d2e3f4a5, finding:static_analysis:unitemised=4, tier:CRITICAL; 0 dispositioned — coverage PASS 13/13 — range v0.6.0@<sha12>..<sha12>
RELEASE-TIER-FINDINGS INDETERMINATE: run-stale (finished 2026-10-14T01:02:03Z, max age 3600s) — no tier or finding verdict produced
```
- Every undispositioned **and** every dispositioned identifier appears, sorted, with no cap and no "and N more" (AC-11, REQ-T8).
- Under ESC-7 a `computed over <k>/<n>; not scored: <names>` clause is inserted after the floors.
- **Later lines:**
  - one row per blocking item: identifier, runner, sanitised path (control characters stripped, at most 120 characters, quoted), line, state, and the disposition URL if any;
  - `DISPOSITION_IGNORED_*` rows;
  - per-runner informational high counts;
  - the full 40-hex base and head, for copying into a disposition;
  - the `OUT` path and seal hash.
- **Exit codes:** `0` PASS or PASS-DISCLOSED; `1` FAIL; `2` INDETERMINATE or a usage error. `main` wraps `try/except BaseException`, and an unexpected exception gives `INDETERMINATE: internal-error:<Type>`, exit 2 (AF-8). The wrapper maps every other code to 2.
- **Amendment to REQ-T10 (AM-4): there is no distinct exit code for PASS-DISCLOSED.** R2/R3 consume exit codes as pass/fail, and every existing suite's non-zero means FAIL. A fourth code would need a three-state R2/R3 *and* a mapping for every suite. The only place disclosure must land is R4 (REQ-T8), and AD-9 puts every passing suite's line 1 there. The PASS-DISCLOSED token is therefore carried on line 1, not in the exit code.

## 9. R2 integration and slicing

### AD-9: a new R2 row directly below #1623's, normative table order, and R4 quotes every suite's line 1 (protected-surface edit)

S4's edits to `.claude/agents/worker.md` (authored by the top-level session only, CLAUDE.md #1347; CODEOWNERS-gated):
1. **R2 table.** Add a row immediately below ADR-1623 AD-6's `release_validator_coverage.sh` row:
   `| \`scripts/oversight/release_tier_findings.sh --issue <n>\` (tier and blocking findings over the release-range run; run after the coverage suite) | required | required |`
   It is required at PATCH and at MINOR/MAJOR (REQ-T11).
2. **Order.** Add one sentence to R2: "Run the required suites in table order." No other suite depends on order today, so the sentence costs nothing elsewhere.
3. **R4 item 1** becomes: "Validation results — for each required suite: script path, exit code, UTC timestamp, followed by a fenced block containing the suite's stdout line 1 verbatim; note any tier-optional suites skipped (PATCH only)." This is the AF-2 fix. It applies to every suite, which also repairs ADR-1623 AD-5's tolerated-loss visibility.
4. **PATCH-promotion sentence.** If ADR-1624 S4 has not already reworded "all five suites" to a count-free form, this S4 does it. Whichever lands first rewords it, and the other leaves it alone.
5. **R1.9.** No change. Check 3 anchors on the new path. A disposition comment is a non-bot comment, so it forces a fresh run of every suite (REQ-T11).

**Composition in R2 for one release request:**
- coverage (#1623) produces the sealed run and verdict 1;
- tier/findings (#1622) verifies the seal and gives verdict 2;
- review evidence (#1624) is independent of both.

One comment from the human can carry `validator:`, `tier:`, `finding:` and `#n`/SHA dispositions together. All three gates read it through the one shared reader (E-1622-1).

### AD-10: test strategy (hermetic; no network, no ScanCode)

- **Seams:**
  - a fixture `OUT/` tree builder that writes outfiles, `dispatch.tsv`, `summary.json`, `files.txt` and a correctly hashed `run-record.tsv`;
  - `release_panel_logic.run_git` (monkeypatched);
  - the shared reader's fetcher (`github._run_gh`, monkeypatched, with canned comment pages);
  - an injected clock.
- **AC-1..AC-15** map one-to-one to tests. AC-13's `overseer.md` grep test is kept, and its docstring says REQ-B7's PR must delete it.
- **Added (binding):**
  - **T-1:** shuffled evidence → identical identifiers. Two identical canonical tuples → `.2` suffix, order-independent (AF-3).
  - **T-2:** a stray `foo.json` in `OUT/` → `run-record-mismatch` (AF-4). A static test asserts the seal filename does not end `.json`.
  - **T-3:** a tampered `summary.json` (one byte) → `run-record-mismatch:summary.json`. `composite_score` edited and the seal re-hashed → `composite-mismatch` (AD-3).
  - **T-4:** a result with `error: ""` and `score: 0.9` → included in the recomputed composite, matching the aggregator (AF-5).
  - **T-5:** `schema.score_to_tier` monkeypatched to drift at 0.55 → `threshold-copy-drift:schema`. A `summary.tier` disagreeing → `threshold-copy-drift:aggregator`.
  - **T-6:** `static_analysis` not scored, coverage human-overridden → `finding:static_analysis:not-scored` blocks (AF-7).
  - **T-7:** `ip_check` with 12 high dependency findings and 10 evidence items → 12 items, no unitemised item. `high_count` = 13 → INDETERMINATE.
  - **T-8:** `static_analysis` and `static_analysis_js` both with high items → distinct runner identifiers (ADR-1623 AF-2).
  - **T-9:** a `tier:HIGH` disposition when the derived tier is CRITICAL → not honoured. `unitemised=4` when k=5 → not honoured. A disposition without `@head` → `DISPOSITION_IGNORED_UNPINNED`.
  - **T-10:** a static test asserts the module has no `0.30`/`0.55`/`0.78` literal and no `--comments`/`--comments-json`/`list_issue_comments` string, and that it never imports `run_validators` or calls `derive_range`.
  - **T-11:** an injected `ValueError` → exit 2, never 1 (AF-8).
  - **T-12 (FU-1 seed, test-only):** a parity test pinning that `schema.TIER_THRESHOLDS` lower bounds, `schema.score_to_tier`, `run_validators.sh`'s `TIERS` (parsed from the file), `require_tier_ceiling._score_to_tier` and `gate_compliance._CRITICAL_THRESHOLD` agree at every boundary. It **edits no protected file**: it only reads them. AM-8 amends REQ-T14/§4: the parity *test* is in scope; *consolidation* stays out of scope.
- **Inner loop:** `scripts/framework/run_tests_inner_loop.sh` passes (AC-15). The per-PR `test_run_validators_*` and `test_require_tier_ceiling` files pass unmodified (AC-12).
- **Demonstration run before S4** (ADR-1340 AD-9 precedent). Two real runs of the coverage suite followed by this gate, at one head, on the live range. Attached to the S4 PR: line 1 of each, the per-item table, and wall clock. The two identifier sets must be identical (AF-3). The measured tier feeds ARCH-ESC-1.

### AD-11: slice plan

| Slice | Content | Files (approx.) | Codable before human answers? |
|---|---|---|---|
| **S0** | **Measurement, no code.** Over #1623 S0's full release-range output (or a run in a `git clone --local` under `mktemp -d`, as in ADR-1623 AF-6), record the composite and derived tier; the per-runner floors; the blocking-item count under ESC-3 (A), (B) and (B)+`historical_density`; the unitemised `k` per runner; and the identifier-set equality of two runs at one head. Use an uncommitted script under `$TMPDIR`. Attach the results to the TD. | 0 | **Yes.** It informs ESC-1, ESC-3 and ARCH-ESC-1. It does not gate S1/S2 structure. |
| **S1** | E-1622-2 in `release_validator_coverage.py`: `run-record.tsv`, plus the exported `classify` / `check_content_pin`. **Folded into ADR-1623 S2 if that is not yet coded.** Tests: seal written last and atomically on each terminal path; never `*.json`; hashes. | 2–3 | **Yes**, once ADR-1623 S1 is on `main`. Not protected (unless ADR-1623 ARCH-ESC-2 = yes). |
| **S2** | `release_tier_findings.{py,sh}`: AD-1..AD-6 and AD-8, with interim constants and `DISPOSITION_SOURCE="none"`; fixtures; AC-1..AC-7, AC-11..AC-15; T-1..T-8, T-10..T-12; `SCRIPTS-INDEX.md` regenerated. Nothing invokes it. | ~8 | **Yes**, after S1 (and ADR-1623 S2) are on `main`. Inert. Every ESC is a constant. |
| **S3** | Disposition wiring: `DISPOSITION_SOURCE="issue-comment"`, AD-7 matching, AC-8..AC-10, T-9. **If no shared reader exists yet, S3 builds `release_dispositions.py` per E-1622-1** (on ADR-1624 S0/S1's `fetch_raw_pages` and assembler), and #1624 S3 / #1623 S3 then import it. | 3–5 | **Partly.** It needs ADR-1624 S0+S1 on `main`. It may assume ESC-4/5 defaults (pm: safe defaults), but those are not binding until the human confirms them. |
| **S4** | **Arming.** Top-level session only. The `worker.md` R2 row, order sentence and R4 item 1 (AD-9). `DECISIONS.md`: ESC-3's narrowing of REQ-B3 and ESC-8 (a)+(b), in the same entry as #1623 ESC-1 and #1624 ESC-1. `docs/OVERSIGHT-RUNBOOK.md`: reading line 1, and the disposition grammar with worked examples. If ARCH-ESC-2 = yes, `scripts/framework/protected_surfaces.txt` plus `gen_codeowners.sh`. | 3–5 | **No.** Waits for ESC-1..8, ARCH-ESC-1..3, S1..S3 merged, #1623 S4 armed (or in the same PR), and the demonstration run (AD-10). |

Merge order: S1 → S2 → S3 → S4. S0 runs first and informs the human's ESC answers; it does not gate code.

**REQ-B8 ordering (REQ-T13).** G-b and G-c are re-homed only when **S4 merges**. #1340's REQ-B7 removal of `overseer.md:170-220` waits for this issue's S4, together with #1623 S4 and #1624 S4. Until then the overseer section is untouched, and AC-13 pins it.

## 10. Protected surfaces

- **Edited:**
  - `.claude/agents/worker.md` (S4 only; top-level session; CODEOWNERS);
  - `scripts/framework/protected_surfaces.txt` and the regenerated `.github/CODEOWNERS` (S4, only if ARCH-ESC-2 = yes).
- **Read, never edited:** `scripts/oversight/validators/schema.py` and `scripts/oversight/run_validators.sh`. T-12 reads both. No runner change is needed. E-1622-2 lives in the checker, not the runner, so ADR-1623 S1's protected runner diff does not grow.
- **New and unprotected unless ARCH-ESC-2:** `release_tier_findings.{py,sh}` and `release_dispositions.py`.

## 11. Requirement amendments (for pm-agent to record; the requirements file is not edited here)

- **AM-1 (REQ-T9.2, F9).** Strike `query_issues.sh --comments-json` as an admissible transport. The only reader is the ADR-1624 AD-7 reader on `fetch_raw_pages` plus the E-1624-1 assembler, built once as `release_dispositions.py` (AF-1, E-1622-1).
- **AM-2 (REQ-T5, ESC-3).** Finding classes are keyed by **runner name**, not dimension. The ESC-3 (B) set is `{static_analysis, static_analysis_js, ip_check, migration_risk, portability}`.
- **AM-3 (REQ-T6).** INDETERMINATE also covers: a missing or malformed seal, a hash mismatch, a run older than `MAX_RUN_AGE_S`, a recomputed coverage verdict disagreeing with the seal, `composite-mismatch`, `threshold-copy-drift`, `result-unparseable`, and an internal exception (AD-2, AD-3).
- **AM-4 (REQ-T10, REQ-T8).** PASS-DISCLOSED is exit 0 with a distinct line-1 token, not a distinct exit code. REQ-T8's disclosure is delivered by R4 quoting every required suite's line 1 (AF-2, AD-8, AD-9).
- **AM-5 (REQ-T7, F7).** `ip_check` is itemised exactly from `raw_value.dependency_findings`/`prompt_findings`; it has no unitemised excess. `static_analysis_js`'s count is `semgrep_error_count`. `historical_density`'s excess is only an upper bound.
- **AM-6 (REQ-T9, new).** Finding identifiers must be identical across two runs at the same head (AF-3). Dispositions carry an explicit `@<head sha40>`. `tier:<T>` is honoured only for the derived tier, and `unitemised=<k>` only at exactly `k`.
- **AM-7 (ESC-7, new).** A blocking runner that did not score yields `finding:<runner>:not-scored`, which a coverage override does not clear (AF-7).
- **AM-8 (REQ-T14, §4).** The threshold-parity **test** (T-12) is in scope, because it edits no protected file. Consolidating the copies stays out of scope (FU-1). The copy count is six code sites, not five (row 5).
- **AM-9 (REQ-T11).** The gate is a separate R2 row, `release_tier_findings.sh --issue <n>`, run after the coverage row. R2's table order becomes normative.

Endorsed as written: REQ-T1, T2, T3, T4, T12, T13.

## 12. Escalations

### Human (pm-agent's; the architect gives a recommended default and does not rule)

| ESC | Architect's recommended default | Technical note | Gates |
|---|---|---|---|
| ESC-1 | **(B)**, conditional on S0 | Mechanically, (B) is exit 0 + `PASS-DISCLOSED` + R4 quoting (AD-8/AD-9), so no third R2/R3 state is needed. Caveat: pm's partial composite was 0.76. If S0 shows the full run is routinely **CRITICAL**, (B) degenerates into (A)'s per-release ritual at CRITICAL. That is ARCH-ESC-1. | S4 binding; S2 interim |
| ESC-2 | **(A)**, concur | The only non-size floors (bandit HIGH, semgrep ERROR) are exactly the `static_analysis(_js)` blocking items under ESC-3 (B), so (A) loses nothing that (B) would catch. (C) is HIGH by construction (F5). | S4; constant |
| ESC-3 | **(B)**, concur. Sub-question: **`portability` in**, **`historical_density` out** | `portability` scored 0.0 in pm's partial run, so including it costs nothing today. It is a real defect class for a shipped framework. `historical_density` is past labelled issues, not a current defect, and its evidence is live-state, which breaks AF-3's identifier stability. | S4; constant |
| ESC-4 | **Head-pinned**, concur | AD-5's identifiers are not designed to survive a head change. "Carry" would need a different identifier scheme (line-independent), so it is not a constant flip. | S3/S4 |
| ESC-5 | **No bulk**, concur | The grammar already rejects `*` and `all` (AD-7). | S3 |
| ESC-6 | **(A)**, concur | Under ESC-3 (B) it only arises when one release carries more than 10 bandit HIGH or more than 10 semgrep ERROR findings. `ip_check` needs no excess item (AM-5). | S4; constant |
| ESC-7 | **Evaluate and disclose**, concur, **with AM-7** | Without AM-7, a coverage override on a blocking runner would silently clear its unknown findings. | S4; constant |
| ESC-8 | **Accept (a) and (b)**, concur | Confirmed: check 4 could never fire (row 3), and check 3 saw two stale artifacts (row 2). The window stays open until S4. | S4 (DECISIONS entry) |

### ARCH-ESC (added by the architect; product-boundary checkpoint)

- **ARCH-ESC-1: if S0 or the demonstration run shows the release composite is CRITICAL on a normal release, what happens at arming?** Under ESC-1 (B), every such release FAILs until the human posts `tier:CRITICAL @<head> — <reason>`. That is a per-release human round-trip, and REQ-B2's per-PR-calibrated tier carries little information at release scale (F6).
  - Options:
    - **(a)** Arm anyway. One disposition line per release, the reason is on record, and a recalibration follow-up issue is filed.
    - **(b)** Defer arming of the *tier* half until a release-scale calibration issue lands. Arm the *finding* half alone, with `TIER_POLICY` all `"disclose"`.
    - **(c)** Treat CRITICAL as disclose-only (ESC-1 becomes "disclose at HIGH and CRITICAL").
  - **Recommended: (a).** It keeps a hard stop exactly where REQ-B2 put it, and the cost is one line. (b) leaves G-b un-re-homed and blocks REQ-B7. (c) drops a guarantee without a REQ-B0(ii) record.
  - This is product-boundary: it changes release latency and the human's per-release workload.
  - Gates: S4.
- **ARCH-ESC-2: add `scripts/oversight/release_tier_findings.{py,sh}` and `scripts/oversight/release_dispositions.py` to `protected_surfaces.txt`?**
  - The constants in AD-6 *are* the human's ESC rulings. Without protection, a worker PR can flip `TIER_POLICY` or shrink `BLOCKING_RUNNERS` with only overseer review.
  - The shared reader decides who may waive a release gate.
  - **Recommended: yes**, decided together with ADR-1623 ARCH-ESC-2 and ADR-1624 ARCH-ESC-3.
  - Gates: S4 (the list edit is itself protected).
- **ARCH-ESC-3: R4 quotes every required suite's line 1 on the authorization comment (AD-9 item 3).**
  - This changes the content of the comment the human reads before authorizing, for every suite, not only this one. It makes the comment longer. It fixes a disclosure gap that also affects #1623 (AF-2).
  - **Recommended: yes.** It is the only mechanism by which REQ-T8 and ADR-1623 AD-5's visibility claim are true.
  - Gates: S4.

## 13. Follow-ups (named, not filed here)

- **FU-1:** consolidate the six threshold copies (row 5) onto `TIER_THRESHOLDS`. This touches `schema.py`, `run_validators.sh`, `require_tier_ceiling.py` and `gate_compliance.py` (all protected or per-PR) and `run_second_review.sh`'s defaults. T-12 pins parity in the meantime.
- **FU-2:** the overseer's dead check 4 (row 3) is removed by REQ-B7. Note that if anyone revives it before then, it must read `evidence` with case-insensitive severity.
- **FU-3:** the composite trusts each result's self-reported `weight`. A validator emitting `weight: 0` drops itself from the tier. Pinning `weight == WEIGHTS[...]` needs a dimension→key map (`complexity` → `"cyclomatic"`), and that is a per-PR change.
- **FU-4:** release-scale calibration of the composite (F6, ARCH-ESC-1).
- **FU-5:** ADR-1623 coordination. AF-6: S3's override needs `--issue`, or delegates to callers as this gate does. §14: AD-5's visibility claim depends on ARCH-ESC-3.
- **FU-6:** release-mode uncapped evidence (ESC-6 (B)), if `unitemised` items prove common.

## 14. Affected sign-offs (startup-gap analysis)

- **Should this have been settled in the initial review?** Partly.
  - R4 never quoting suite output (AF-2) is a property of NG3b's original design. It became a defect only when suites began carrying verdict text on line 1 (ADR-1623, ADR-1624). This is the same `startup-artifact-gap` family as ADR-1340 AF-1 / ADR-1624 §15, not a new class.
  - **Recommended:** the orchestrator annotates #1340. Per this cycle's constraints the architect files nothing.
- **These sign-offs stand:**
  - ADR-1623 AD-1..AD-4 and AD-6. E-1622-2 is additive inside S2, and nothing is coded.
  - ADR-1624 AD-1..AD-6. AD-7's grammar is extended additively, so its existing items behave unchanged.
  - ADR-1340 AD-2.
- **These are re-opened (no code exists, so nothing is orphaned):**
  - ADR-1623 AD-5's claim that a tolerated-loss PASS is visible. It is true only after ARCH-ESC-3's R4 change.
  - ADR-1623 AD-1's "no arguments", for S3 only (AF-6).
  - ADR-1624 AD-7's reader location: it moves to the shared `release_dispositions.py` (E-1622-1).

  Whoever writes the TD for ADR-1623 S2/S3 and ADR-1624 S3 must take these into account.

---

## Human Review Required

**RISK: HIGH.** This is a release gate at every tier. It edits a protected agent file (S4) and changes the human's authorization comment for every suite.

Four ways it could have passed wrongly are closed positively:
- forged or edited dispositions, and dispositions truncated past page 1 (AF-1 → the shared strict reader);
- a stale or foreign run read as the candidate's (AF-4 → seal, hashes, head, age, re-classified coverage);
- threshold or composite drift (AD-3 → runtime parity and an exact recompute);
- a coverage override silently clearing unknown findings (AF-7).

Two ways it could have failed uselessly are closed:
- dispositions that never match after the fresh run they trigger (AF-3 → stable identifiers);
- a HIGH-by-construction floor gate (ESC-2 (A)).

**CONFIDENCE: 80%.**
- High on §0: every row was read or measured this session.
- High on AD-1..AD-5, AD-7 and AD-8.
- **Medium on the identifier-stability premise for `ip_check` and bandit** (that the same head gives the same messages). It is unmeasured, which is why the demonstration run's two-run equality is a binding S4 precondition.
- **Medium on whether the full release composite is CRITICAL** (ARCH-ESC-1). That is unmeasured until S0.

**BLAST RADIUS.**
- S1: `release_validator_coverage.py` (additive seal).
- S2/S3: new inert modules.
- S4: whether any release can be cut, at every tier; the content of every R4 authorization comment; the human's per-release disposition workload.
- No per-PR effect (REQ-T12): nothing per-PR is edited.

**Change classification: STRUCTURAL.** It adds a new blocking condition at every tier, a human disposition step, a formal narrowing of REQ-B3 (ESC-3), a change to the human-facing authorization comment (ARCH-ESC-3), and protected-surface edits. Per the product-boundary checkpoint, ESC-1..8 and ARCH-ESC-1..3 must clear before S4 binds. S0–S2 may proceed now. S3 may proceed on ESC-4/5 defaults once ADR-1624 S0+S1 are on `main`.
