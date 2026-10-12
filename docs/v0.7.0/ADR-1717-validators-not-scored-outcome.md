# ADR-1717 — The validators' "not scored" outcome

Issue: #1717 (bug, priority:high, v0.7.0). Author: architect. Date: 2026-10-12.
Input: `docs/v0.7.0/REQUIREMENTS-1717-validators-not-scored-tier.md` (pm-agent).
Status: **Accepted (technical)**. ESC-1 and ESC-2 stay open for the human. Neither blocks S1, S2 or S3 (§8).

## Context (verified against the code, 2026-10-12)

`run_validators.sh:465-483` fail-closes (`composite 1.0`, `CRITICAL`, exit 1) when `total_w == 0`.

**Premise correction (TD review round 4, security-reviewer M1, CWE-693).** The original text said "on a docs-only diff that adds a new file, every weighted validator returns `error: "no input files"`". That is **wrong**.
- The weighted validators report N/A only when **none of their argv paths exist** (`[f for f in argv if Path(f).exists()]`: `migration_scorer.py:184`, `issue_query.py:240`, `ip_check.py:516`). File type plays no part.
- A new `.md` file scores (historical_density 0.03 → LOW on this branch's own run).
- All-weighted-N/A therefore means **no changed path exists in the working tree**. That happens in three cases:
  - (i) a deletion-only diff;
  - (ii) a git-quoted path (`git diff --name-only` at `:85` without `-z`/`core.quotepath=false`, so `é.py` becomes `"\303\251.py"`, which never exists);
  - (iii) running the validators in a checkout that lacks the PR's files (the probable #1716 repro).

Only (i) is a measurement. (ii) is a runner bug, and (iii) is unreadable evidence. D6 conditions 6-7 and D9 encode this.
`diff_size` scores, but its weight is 0. So a run that measured nothing wrong is labelled CRITICAL.
I checked each consumer claim the pm-agent made:

| Reader | Verified behaviour on an unknown tier, or a `null` composite |
|---|---|
| `merge_authority.RiskTier.from_str` (`:301`) | `cls[s.upper()]` raises `KeyError`. Reached from `pr_readiness._tier_gte` (`:219`) and `merge_config` (`:94`) |
| `run_review_chain.sh resolve_tier` (`:176-179`) | `die "Unrecognized tier"`. **Fails closed** |
| `require_tier_ceiling._try_validator_summary` (`:162-173`) | Unknown → `None` → structural fallback, which **can yield LOW. This path fails open** |
| `run_second_review.sh:196-201` | `print(d.get('composite_score', 0))`. A `null` composite becomes the string `None`, then `select-reviewers --score` (`type=float`) exits 2, and the caller fails closed (`:221-225`). A *missing* key, or any read failure, gives `0`. That is a pre-existing fail-open, recorded as follow-up F-2 |
| `second_review_logic` digests (`:996`, `:1020`) | Pass the composite through unchanged. A `null` is safe there only if the digest consumers handle `None` (S1 must test this) |
| `release_artifact_logic.check_artifact_integrity` (`:157-161`, `:217`) | A non-numeric composite is an integrity error. **Fails closed** |
| `pr_readiness._check_validators_current` (`:376-381`) | `composite is None` gives "missing composite_score", so REQ-W-03 fails. **Fails closed**, with the wrong reason |
| `gate_compliance.load_composite_score` / NN-17 (`:58-73`, `:173`) | `None` means NN-17 does not trip. That is already the correct response |
| `run_panel.sh` release mode (`:426-430`) | `jq '.tier // "unavailable'`. The sentinel passes through as text and the MEDIUM clamp still applies |

Also verified:
- `run_validators.sh` runs under `set -euo pipefail`. The aggregate heredoc's `sys.exit(1)` therefore aborts the script **before** the committed `signoffs/validators/step{N}/summary.json` (#555) is written. This matters for D5.
- All 16 emitter files write the exact literal `"no input files"`: 16 `error=` keyword arguments, plus 2 raw_value dict literals in `ip_check` and `prompt_audit_risk` (grep of `validators/`, corrected in TD review round 1, AQ-1).
- An optional validator that exhausts its retries is counted `VALIDATOR_SKIPPED` by the shell (`:261-265`), but its outfile carries `error: "validator exhausted retries"`. The requirements' "Skipped" and "Errored" definitions overlap at exactly this case. D3 resolves the overlap.

## Decisions

### D1 — Representation: a sentinel tier and a null composite, plus an explicit outcome field

A not-scored `summary.json` carries:
```
"scoring_outcome": "not_scored",          # every aggregate-written summary: scored | not_scored | fail_closed
"tier": "NOT_SCORED",                      # sentinel, outside LOW..CRITICAL
"composite_score": null,                   # never a number on this outcome (REQ-07)
"not_scored_reason": "no weighted dimension applied: deletion-only docs diff (2 path(s)); not applicable: historical_density, ip_check, migration_risk",
"validator_outcomes": {"<name>": "scored|not_applicable|errored|skipped", ...},
"tier_floor": "<max floor>"                # if any validator emitted one (D4)
```
Scored and fail-closed summaries also get `scoring_outcome` and `validator_outcomes`. They are additive keys. `composite_score`, `tier` and `tier_floor` stay byte-identical (REQ-04). The pre-aggregation paths (`:142`, `:185`) are untouched (REQ-05). The helper treats a missing `scoring_outcome` as legacy and derives it from `tier`.

**Why a sentinel.** A fail-closed design wants every reader that does not know about the new state to hit its *unknown-value* path. A sentinel tier does exactly that. The table shows that every unaware reader except one then fails closed, either by crashing or by rejecting the value. The exception is `require_tier_ceiling`, which falls back to its structural estimate. That makes the fail-open set finite and named, and S1 closes it before the producer ever emits the sentinel (§8 ordering).

**Rejected alternatives:**
- **(a) Keep `tier: CRITICAL` (or composite 1.0) and add a side field.** Unaware readers would behave exactly as they do today, so blast radius would be zero. But it keeps the false CRITICAL in the field every reader acts on. That violates REQ-02 and REQ-07, and gate_compliance NN-17 would keep tripping on a 1.0. It hides the bug rather than fixing it.
- **(b) Write the effective tier (for example MEDIUM) into `tier`, plus a side field.** An unaware reader would treat MEDIUM as *measured*, which is the "silent tier" REQ-07 forbids. It would also bake the ESC-1 policy into every committed artifact, so flipping the policy would leave stale artifacts behind.
- **(c) `composite_score: 0.0`.** This reads as measured LOW to second-review selection and to the release sweep. That is fail-open.

**The tension, stated plainly.** Fail-closed and "no false CRITICAL" pull in opposite directions. This design resolves the tension *per reader*, not globally:
- An unaware reader fails closed. It errors or rejects; it never auto-passes.
- Only a reader that has been taught the sentinel through the D7 helper relaxes from CRITICAL.
- Until ESC-1 is ruled, even aware readers keep today's CRITICAL-equivalent behaviour (D7).

The cost of this design is that each unaware reader crashes instead of degrading gracefully. S1 exists to convert those crashes into defined responses (REQ-13).

### D2 — N/A detection: exact match on one named constant; a structured field is deferred

N/A means `result["error"] == NOT_APPLICABLE_ERROR`, where `NOT_APPLICABLE_ERROR = "no input files"` is defined once in the new helper (D7).
- Any other `error` value, an outfile that does not parse, a non-dict outfile, or an invoked validator with no outfile is **errored**.
- No substring matching, no case folding and no whitespace stripping (REQ-01).

S1a adds a test that pins every `"no input files"` literal in `scripts/oversight/validators/*.py` to the constant. If an emitter drifts, the test goes red; it does not silently reclassify the result as errored.

**Rejected: a structured `status: "not_applicable"` field in `schema.make_result` now.** It would touch 16 validator envelopes, and the `error` key would still have to stay because composite exclusion keys on it. That makes two signals that can disagree. Migrating emitters to import the constant, or to a structured status, is follow-up **F-1**. It is not in scope.

### D3 — Python classification is the single source of truth for the console counts

The aggregate block classifies every result once, and prints the counts line from that classification:
`Validators: S scored, N not applicable, E errored, K skipped`.

The shell's `VALIDATOR_SUCCEEDED` / `VALIDATOR_SKIPPED` line at `:427` is removed. `VALIDATOR_FAILED` stays as the required-failure signal that #1752 owns.

The definitions, which resolve the overlap noted in Context:
- **skipped**: no outfile exists because the script is absent. The shell passes these names to Python through an env var.
- **errored**: an outfile exists and carries any `error` other than N/A. An optional validator that exhausted its retries is therefore *errored*, not skipped: it was expected to measure something and could not (REQ-01 governs).

A test asserts that the counts line and the verdict line can never contradict each other (AC-3).

### D4 — tier_floor

Hoisting is unchanged on a not-scored run: the same MAX-by-rank loop as `:500-506`. The runner never folds the floor into `tier`.
- The effective tier is `max(base, tier_floor)`, computed only by the D7 helper (REQ-08).
- An unrecognised floor string on a not-scored run makes the effective tier CRITICAL.
- A not-scored run requires that no result errored **and no validator was skipped** (D6, conditions 3 and 5). Losing `diff_size` (weight 0), whether it errors or its script is absent, therefore cannot quietly drop the floor. *(Amended in TD review round 2, AQ-4: the original wording covered errored results only, and a skipped validator leaves no outfile to error.)*

### D5 — Exit code 0

A not-scored run exits **0**. The script header documents three outcomes: 0 = scored or not-scored, 1 = fail-closed. The outcome itself is read from `scoring_outcome`.

Exit 0 is also *required* for REQ-09. Under `set -e`, a non-zero exit from the heredoc aborts the script before the #555 committed artifact is written.

**Rejected: a distinct non-zero code such as 3.** It would need errexit plumbing around the heredoc. It would also break callers that treat any non-zero exit as failure, while adding nothing that `scoring_outcome` does not already carry.

### D6 — ESC-3 ruled (technical): any errored result plus no weighted score is CRITICAL

The run is **not scored** only if all seven of these hold:
1. at least one result exists;
2. **zero** weighted results scored;
3. **zero** results errored, of *any* weight;
4. at least one weighted result is N/A;
5. **no** validator was skipped, meaning no script was absent (`run_validators.sh:222-225`). The fail-closed reason is `skipped: <names>`. *(Added in TD review round 2, AQ-4.)* "Skipped" here means script-absent only. A validator the runner's file-type routing never invoked is not skipped, and must not be passed as one.
6. every changed path is resolved: it either exists in the working tree or is a confirmed deletion (D9). An unresolved path → `fail_closed`. *(Added in round 4, SEC-M1.)*
7. every changed path is a **confirmed deletion of a non-protected docs-class file** (`.md`/`.rst`, not matching `protected_surfaces.txt`). A deletion of anything else, or a present path that produced no weighted score, → `fail_closed`. *(Added in round 4, SEC-M1.)* After the premise correction, the not-scored outcome is exactly "a deletion-only docs diff". Every other way to reach zero weighted scores is either unreadable, or an unmeasured deletion that a lowered ESC-1 base would under-tier.

Every other zero-weighted-score run stays `fail_closed` (composite 1.0, CRITICAL, exit 1).

"Weighted" means:
- the numeric `weight` on the result when it is present;
- otherwise `schema.WEIGHTS[dimension]`;
- otherwise unknown, which counts as weighted (conservative).

This is stricter than the requirements in three places:
- **Errored, of any weight.** In a run with no composite, the floors are the only signal, so an unreadable unweighted validator is still unreadable evidence.
- **At least one weighted N/A (condition 4).** A run that saw no weighted dimension at all is a routing anomaly, not a measurement.
- **Resolved, docs-only deletions (conditions 6-7).** Without them, a deletion-only diff removing a gate, a workflow or tests, a quoted-name executable, or a wrong checkout would all satisfy conditions 1-5. Under ESC-1 = MEDIUM, any of those would gain a lower tier (security M1).
- **No skipped validator (condition 5).** A script-absent validator produces no outfile, so neither condition 3 nor floor hoisting can see it. It is an install defect, not a measurement. The runner's names do not map to `WEIGHTS` keys, and there is no registry of which dimensions bear floors, so the rule is "any skipped". A rule limited to weighted or floor-bearing dimensions would have to guess.

Runs with at least one weighted score are unchanged (REQ-04).

### D7 — ESC-1 isolated to one constant; interim behaviour equals today's

New stdlib-only module `scripts/oversight/validator_outcome.py`. It is the only code that knows the sentinel:
- `NOT_APPLICABLE_ERROR`, `NOT_SCORED = "NOT_SCORED"`, and `classify(result) -> outcome`, which the runner imports;
- `effective_tier(summary) -> "LOW|MEDIUM|HIGH|CRITICAL"`:
  - tier in LOW..CRITICAL, and the summary is consistent → returned unchanged (no floor folding; existing semantics kept). `scoring_outcome: fail_closed`, or any inconsistency, → `CRITICAL` (TD C-4, `check_consistency`);
  - tier is `NOT_SCORED` → `max(NOT_SCORED_BASE_TIER, tier_floor)`;
  - anything else (missing, a non-string, an unknown string, a non-dict summary) → `CRITICAL`;
- a CLI, `effective-tier <summary.json>`, for shell scripts and agent prose.

**The single decision point is `NOT_SCORED_BASE_TIER`.**
- **Interim value: `"CRITICAL"`.** This is option A: HUMAN_REQUIRED, now with an honest "not scored: <reason>" in place of "all validators failed". It is behaviour-equivalent to today for merge authority and for second-review cost.
- **Architect's recommended default: `"MEDIUM"`.** This is option C. It mirrors the panel's AD-6 clamp, stays within `OVERSEER_CEILING=HIGH`, and adds one agy review per docs PR.

Switching to MEDIUM changes user-visible merge behaviour (docs PRs auto-merge), the cost model (agy calls) and the human-gate load. Under the CORE product-boundary checkpoint, that switch is the human's call. Once the human rules, the flip is slice **S4**: one constant and one test.

Consumers call the helper **only** for summaries that need it: the sentinel under any legacy tier key, any `scoring_outcome` other than exactly `"scored"`, or a non-dict summary (TD `needs_helper`). For a legitimate value on any other path, their existing handling stays byte-identical (blast radius).

*(Amended in TD review round 2.)* This blast-radius guard protects **legitimate** values only. It does not preserve fail-opens on malformed input. Specifically, in `require_tier_ceiling`, a summary file that is present but yields no tier in LOW..CRITICAL under any legacy key resolves to `CRITICAL`, never to the structural fallback. That covers an unreadable file, non-JSON, a non-dict, and a dict with no valid or an unknown tier. No legitimate producer path writes such a summary, so nothing that works today changes. The CLIs that take a tier argument stay as they are, rejecting `NOT_SCORED` as they already do:
- `pr_readiness --risk-tier`, `pr_review_cli --tier`, and `merge_authority` via `from_str`;
- agents pass these CLIs the helper's effective tier (S3).

### D9 — Path facts (added in round 4, SEC-M1)

The runner (S2) classifies every changed path as `present`, `deleted_docs`, `deleted_other` or `unresolved`. It passes these to the helper's `decide_zero_weight_outcome(..., path_facts=...)`, which is keyword-only with no default; `None` or empty → `fail_closed`. The helper stays pure: it does no I/O and no glob matching.
- In `--diff` mode the paths come from `git -c core.quotepath=false diff -z --no-renames --name-status`, where `D` = deletion. The same list replaces `:85`'s `ALL_FILES` source, which also stops quoted names silently dropping out of scored runs.
- In explicit-list mode no deletion is ever confirmed.
- Protected-ness reuses `require_human_approval.load_globs` / `matched_surfaces`, never a second glob implementation. A load failure counts as protected.
- Every summary gains the additive key `unresolved_paths`. On scored runs it is informational (REQ-04). The tier consequence on scored runs is follow-up F-5.

**Rejected: keying ESC-1 by file class (security option b).** It would move class logic into `effective_tier` and add a summary field the readers must trust. Condition 7 gets the same safety with no new reader surface, because a non-docs deletion simply never becomes not-scored.

### D8 — Reconciliation with #1752 (unpushed branch `worker-1752-…-844742`, head `2d302e653`)

#1752 adds `failed_validators` and `skipped_validators`. These are built from shell env lists, and its `skipped` set includes optional retry-exhaustion, which conflicts with D3. **The reconciled field set:**
- `validator_outcomes`, the canonical map.
- `failed_validators`, kept, but **derived** in Python as `required ∧ errored`. Required-ness comes from #1752's `HOS_VALIDATORS_FAILED_REQUIRED`.
- `skipped_validators`, kept, but **derived** as `outcome == "skipped"`. It is no longer an independent shell list.

There is one classification and every other list is a view of it.

**Ordering.** #1717 S2 does not depend on #1752. #1752 is blocked on the pip-audit human question. Whichever merges second rebases onto the other and applies this field set. If #1752 merges first, S2 converts its two lists into derived views. If S2 merges first, #1752's adopter must replace its env-list `skipped_validators` with the derived view. Both edit `run_validators.sh:427-483`, so expect a textual conflict.

## Slices (each ≤ 15 files; consumers before producer)

| Slice | Content | Files (approx.) | Codable before any human ruling? |
|---|---|---|---|
| **S1a** | `validator_outcome.py` (D2/D6/D7, interim `CRITICAL`) and its CLI. Sentinel handling through the helper in: `require_tier_ceiling.py` (closes the one fail-open), `release_artifact_logic.py` (valid artifact, reported as not scored), `pr_readiness.py` REQ-W-03 (a null composite is valid when `scoring_outcome == not_scored`), `second_review_logic.py` digests (null composite). A NN-17 test for gate_compliance. Tests for each | ~11 | **Yes** |
| **S1b** | `run_second_review.sh` (on not-scored, select reviewers from the effective tier and never coerce `null` to a measured score), `run_review_chain.sh resolve_tier` (map through the helper and log "not scored"), `run_panel.sh` release mode (record as not scored, not "unavailable"). `cut_release.sh` inherits from S1a. Tests | ~6 | **Yes** |
| **S2** | Producer: the `run_validators.sh` aggregate (D1/D3/D4/D5/D6), header docs, the counts line, the env pass-through for skipped names. REQ-15..18 regressions, a scored-run byte-identity fixture. `docs/OVERSIGHT-RUNBOOK.md` | ~5 | **Yes to code. Must not merge before S1a and S1b.** If the producer emits the sentinel first, `require_tier_ceiling` fails open |
| **S3** | Protected surface: `.claude/agents/overseer.md` (step 3b plus a "Composite not scored: <reason>" clause in the exec summary, REQ-14), `risk-assessor.md:102`, `oversight-evaluator.md` (it also reads composite and tier). Each tells the agent to obtain the tier through `validator_outcome.py effective-tier` | 3 | Yes to author. CODEOWNERS human approval is required to merge |
| **S4** | ESC-1 flip: set `NOT_SCORED_BASE_TIER` to the ruled value, update the test, update the S3 prose if needed | 2-3 | **No. Waits for the ESC-1 ruling** |

S1a and S1b can merge together or in either order. S2 merges after both, and its PR must cite their merge SHAs.

## Follow-ups (not this issue)

- **F-1**: emitters import `NOT_APPLICABLE_ERROR`, or move to a structured `status` in `schema.make_result`.
- **F-2**: `run_second_review.sh:197-201` gives score `0` when the key is missing or unreadable. That is a pre-existing fail-open, independent of #1717. File it if no existing issue covers it.
- **F-3**: `schema.composite_score()` returns `0.0` on zero total weight (`schema.py:102`). It has no current runtime caller, but it is a fail-open trap for future callers. It should raise, or return `None`.
- **F-5 (round 4)**: unresolved paths on a *scored* run (partial wrong checkout). S2 records them in `unresolved_paths`. Whether they should raise the tier is a separate decision, deferred to keep REQ-04.
- **F-4 (from ESC-2)**: an optional docs/markdown scoring dimension.

## Affected sign-offs

This ADR is new, not a revision of an earlier decision, so there are no prior #1717 sign-offs to orphan. The #1752 branch is code-reviewed (round 2). Its approval stands for its own behaviour, but its adopter must re-run code review on the D8 rebase delta. It is not a startup-artifact gap: the not-scored state was never decided before, so nothing was built against a superseded decision.

## Escalations remaining (human)

- **ESC-1 (reframed in round 4)**: the value of `NOT_SCORED_BASE_TIER`, which now applies **only** to a resolved, deletion-only diff of non-protected `.md`/`.rst` files (D6-7). Candidates are `MEDIUM`, `HIGH` or `CRITICAL`. `LOW` is excluded by REQ-02/REQ-07 (no fabricated LOW). Any other zero-weight run is `fail_closed` CRITICAL whatever the ruling. The interim value `CRITICAL` (option A) ships in S1a. The architect recommends `MEDIUM` (option C). Product-boundary checkpoint: this changes merge behaviour, agy cost and human-gate load. It blocks S4 only.
- **ESC-2 (reframed in round 4)**: is "not scored" the legitimate steady state for a deletion-only docs diff (recommended: yes)? Docs PRs that add or edit files are scored today, so F-4 (a docs scoring dimension) is about the quality of the score, not about coverage. It blocks nothing.
- ESC-3 is **ruled** (D6) and is not an escalation.
