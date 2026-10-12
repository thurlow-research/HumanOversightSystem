# REQUIREMENTS-1717 — "No weighted dimension applied" must not be reported as CRITICAL

Issue: #1717 (bug, priority:high, milestone v0.7.0). Author: pm-agent. Date: 2026-10-12.
Class: same as #1670 — a gate must not confuse *unreadable/unmeasured* with *unsafe*.
Change classification: the new "not scored" outcome is **new behavior** → structural;
its merge-authority response is gated on a human ruling (ESC-1) before coding that part.

## Premise correction (2026-10-12)

Security review found, and the architect verified and ruled (ADR-1717 amended
Context/D6/D9; TECHNICAL-DESIGN-1717 "Architect review (round 4)"), that the issue's
premise is wrong. `historical_density`, `ip_check` and `migration_risk` report
`"no input files"` only when **none of the paths passed to them exist in the working
tree** (`Path(f).exists()` filter: `issue_query.py:240`, `ip_check.py:516`,
`migration_scorer.py:184`), not because of file type. A new `.md` file in a correct
checkout therefore **already scores** today, so issue #1717's AC-1 scenario is not a
real failure. The observed #1716 CRITICAL most plausibly came from running validators
in a checkout that lacked the PR's file. Under these requirements that case stays
fail-closed, but with an accurate "unresolved paths" reason (REQ-1717-21). NOT_SCORED
is narrowed to a **deletion-only diff of non-protected `.md`/`.rst` files**.

## Problem (restated as product behavior)

`scripts/oversight/run_validators.sh` aggregation (inline Python, `:456-483`) excludes
every result carrying an `error` key from the weighted composite, then fails closed
(`composite 1.0`, `tier CRITICAL`, exit 1, "no validators succeeded") when
`total_w == 0 or not successful`. When none of the paths passed to the weighted
validators exist in the working tree (a deletion-only diff, git-quoted non-ASCII paths
that do not resolve, or a checkout that lacks the PR's files):

- `historical_density` (`issue_query.py:249`), `ip_check` (`ip_check.py:525`) and
  `migration_risk` (`migration_scorer.py:193`) run, find none of their paths on disk,
  and report `error: "no input files"`. For a confirmed deletion nothing failed; for a
  path that should exist but does not, the input is **unresolved**.
- The only validator that scores is `diff_size`, whose weight is `0.0` by design
  (`validators/schema.py:76`, "inert in composite; floor is a discrete signal (#377)").
- So `total_w == 0` and the run is labelled CRITICAL with a misleading reason. The overseer's
  `decide_merge_authority()` (`merge_authority.py:642`) compares that tier to
  `OVERSEER_CEILING` (HIGH) → HUMAN_REQUIRED + `needs-human`, even on a benign
  deletion-only docs PR.
- The shell counter (`run_validators.sh:253`) counts any exit-0 validator as
  succeeded, so the run prints "Validators: 4 succeeded" immediately before
  "ERROR: no validators succeeded". Both statements cannot be true.

## Definitions (binding for every requirement below)

- **Scored** — the validator ran and produced a usable score for at least one input.
- **Not applicable (N/A)** — the validator ran and **none of the paths passed to it
  exist in the working tree**, and every such path is a confirmed deletion (see
  Unresolved path). Today this is the exact `error: "no input files"` self-report.
  (A validator the runner deliberately does not invoke by file-type routing produces
  no result and is outside this classification.)
- **Unresolved path** — a changed path passed to validators that does not exist in the
  working tree and is **not** a confirmed deletion in the diff (e.g. wrong checkout,
  git-quoted non-ASCII path that does not resolve). An unresolved path is **Errored**,
  never N/A.
- **Errored** — the validator was expected to measure something and could not: crash,
  timeout, exhausted retries (`run_validators.sh:256`), non-JSON output, or a
  self-reported failure other than "no input files" (e.g. `migration_scorer.py:141`
  "all migration files unparseable"). Errored is **unreadable**, which is *not* the
  same as N/A and must keep fail-closed weight.
- **Skipped (optional)** — script absent or optional-validator failure as already
  counted by `VALIDATOR_SKIPPED`; unchanged by this issue.
- **Not scored (run-level)** — at least one validator ran, **no weighted** validator
  scored, **no weighted** validator errored (every weighted dimension was N/A), **and
  every changed path is a confirmed deletion of a non-protected `.md`/`.rst` file**
  (protected = listed in `scripts/framework/protected_surfaces.txt`).
- **All-failed (run-level)** — no validator scored, or every weighted dimension that
  was expected to apply errored. Unchanged fail-closed CRITICAL.

## Requirements

### Classification and run outcome

- **REQ-1717-01** The runner MUST classify every validator result as exactly one of
  Scored / N/A / Errored / Skipped, using the definitions above. N/A MUST be
  recognised only from an explicit, exact signal (today: `error == "no input files"`,
  or a structured equivalent the architect defines); any other `error` value, an
  unparseable result, or a missing result for an invoked validator is Errored.
  Substring or fuzzy matching of error text is forbidden.
- **REQ-1717-02** A run where every weighted validator is N/A, at least one validator
  ran, none errored, and every changed path is a confirmed deletion of a non-protected
  `.md`/`.rst` file MUST produce the **not-scored** outcome — never tier CRITICAL
  on that ground, and never a fabricated LOW/SAFE tier or score.
- **REQ-1717-03** A run with no Scored validator at all, or where the absence of a
  weighted score is caused (wholly or partly) by an Errored weighted validator, MUST
  still produce the existing fail-closed result: composite 1.0, tier CRITICAL,
  non-zero exit, summary written. (Conservative default: a mix of N/A and Errored with
  zero weighted scores is CRITICAL — see ESC-3.)
- **REQ-1717-04** Runs with at least one Scored weighted validator MUST be byte-for-
  byte unchanged in `composite_score`, `tier` and `tier_floor` (N/A and Errored
  weighted validators remain excluded from the average, as today).
- **REQ-1717-05** The "no files provided" (`:138-148`) and the other pre-aggregation
  fail-closed paths (`:185-191`) are out of this issue's change and MUST remain CRITICAL.

### summary.json contract

- **REQ-1717-06** A not-scored summary MUST state the outcome explicitly and
  machine-readably, carry a human-readable `reason` naming the N/A validators, and
  list per-validator classification. Representation (sentinel tier value such as
  `NOT_SCORED`, or a separate status field) is the architect's decision, subject to
  REQ-1717-07..09.
- **REQ-1717-07** No existing consumer may read a not-scored summary as LOW, SAFE, or
  as a measured score. In particular `composite_score` MUST NOT be a number that any
  consumer interprets as measured risk (neither `0.0` nor `1.0` presented as measured).
- **REQ-1717-08** `tier_floor` MUST still be hoisted on a not-scored run (max across
  validators, as `:500-515`). The effective tier any gate acts on MUST be no lower than
  `tier_floor` (e.g. a large docs diff whose `diff_size` floor is HIGH is gated at
  least HIGH).
- **REQ-1717-09** The committed artifact `signoffs/validators/step{N}/summary.json`
  (#555) MUST carry the same outcome; `head_sha`/`head_sha_source` semantics unchanged.
- **REQ-1717-10** A not-scored run MUST NOT exit with the fail-closed exit code (it is a
  deterministic, successful measurement of "nothing weighted applied"). Exact code is
  the architect's call; it MUST be documented in the script header.

### Operator-visible output

- **REQ-1717-11** The console summary line MUST use the same classification as
  summary.json, counting Scored, N/A, Errored and Skipped separately. A run MUST NOT
  print any count of "succeeded" that contradicts its own final verdict line (AC-3).
- **REQ-1717-12** The final verdict line MUST distinguish the three outcomes: scored
  (`Composite … → tier X`), not scored (with reason), and fail-closed CRITICAL.

### Consumer obligations (every summary.json `tier` / `composite_score` reader)

- **REQ-1717-13** Each consumer below MUST have a defined, tested response to a
  not-scored summary. Where a consumer cannot interpret it, it MUST fail closed (treat
  as unknown → its existing fail-safe path), never crash with an unhandled exception
  and never coerce to LOW.

| Consumer | Today | Required not-scored response |
|---|---|---|
| `merge_authority.decide_merge_authority` / `RiskTier.from_str` (`:293-303`, `:642`) | unknown string → `KeyError` | Per ESC-1 ruling; never AUTO_MERGE as LOW |
| `pr_readiness.py` (`--risk-tier` choices, `_tier_gte` `:217`) | rejects unknown tier | Operates on the effective tier per ESC-1; REQ-W-08 second review applies if effective ≥ MEDIUM |
| `pr_review_cli.py` `--tier` (`:159-166`) | usage error on unknown | Accepts the effective tier; never a silent coercion |
| `require_tier_ceiling.py` `_try_validator_summary` (`:162-173`) | unknown → `None` → structural fallback | Must not be read as within-ceiling LOW; fallback/effective tier per ESC-1 |
| `run_second_review.sh` (`:196-202`) / `second_review_logic.py` digests (`:974-1021`) | `float(composite_score)`; `null` would break | Reviewer selection from effective tier; no crash on non-numeric composite |
| `run_review_chain.sh` `resolve_tier` (`:155-178`) | `die` on unknown tier | Defined mapping to effective tier, logged as not-scored |
| `run_panel.sh` release mode (`:417-437`) | non-zero exit / unknown → "unavailable" | Recorded as not-scored (not "unavailable"); MEDIUM clamp AD-6 still applies |
| `gate_compliance.load_composite_score` / REQ-GATE-NN-17 (`:58-73`, `:172`) | ≥ 0.78 → deterministic CRITICAL | Not-scored never trips NN-17; absence is not a compliance failure |
| `release_artifact_logic.py` `check_artifact_integrity` (`:148-162`, `:216-218`) | non-numeric composite → integrity error | Valid artifact; reported as not-scored; blocks release only if effective tier is HIGH+ with blocking findings (existing rule) |
| `scripts/framework/cut_release.sh` sweep (`:193+`) | via release_artifact_logic | Same as above |
| `signoff_gate.py` | no tier read found | Verify-and-record: confirm no dependency |
| `.claude/agents/overseer.md` (step 3b, exec summary `:657-663`), `.claude/agents/risk-assessor.md` (`:102`) | read composite/tier as prose | Must name the not-scored state and its reason; risk-assessor still promotes by floor/semantics (protected surface — human gate) |

- **REQ-1717-14** The executive summary the overseer posts on a not-scored PR MUST say
  the composite was not scored and why (which dimensions were N/A), consistent with
  the existing "Not verified this run" clause convention.

### Tests (acceptance)

- **REQ-1717-15** Regression: a deletion-only diff of non-protected `.md`/`.rst`
  files → not-scored outcome, not CRITICAL, consistent counts (AC-1 as corrected, AC-3).
- **REQ-1717-20** Regression: a diff adding a **new** `.md` file (no churn history) in
  a correct checkout → **scored** (normal composite and tier), not not-scored and not
  CRITICAL. Guards the premise correction.
- **REQ-1717-16** Regression: every invoked validator errors/times out → CRITICAL,
  exit non-zero (AC-2). Also: N/A + Errored weighted mix with zero weighted scores → CRITICAL.
- **REQ-1717-17** Not-scored run with a `diff_size` `tier_floor` of HIGH → floor
  preserved in summary and effective tier ≥ HIGH.
- **REQ-1717-18** A non-"no input files" `error` string (e.g. migration unparseable)
  is Errored, not N/A.
- **REQ-1717-19** Each consumer in the REQ-1717-13 table has a test feeding a
  not-scored summary and asserting the defined response (AC-4); a scored-run fixture
  proves REQ-1717-04 unchanged.

### Path resolution (appended after the premise correction)

- **REQ-1717-21** Any unresolved path MUST make the run fail closed (CRITICAL,
  non-zero exit), and the summary `reason` MUST name the unresolved paths, not "no
  validators succeeded". Tested with a checkout that lacks a changed file.
- **REQ-1717-22** A deletion-only diff that deletes any non-docs file (anything other
  than `.md`/`.rst`) or any protected-surface path MUST fail closed; it is never
  not-scored. Tested for both cases.
- **REQ-1717-23** The runner MUST collect changed paths unquoted (non-ASCII paths are
  not git-quoted, e.g. `core.quotePath=false` or `-z`), so a non-ASCII path that exists
  resolves and scores. Tested with a non-ASCII filename.

## Non-goals

- Adding a weighted dimension that scores docs deletions (separate follow-up if wanted;
  added or modified docs already score via existing validators).
- Changing weights, tier thresholds (`:487`), or `diff_size`'s zero weight.
- Changing pre-aggregation fail-closed paths or required-validator failure messaging
  (owned by #1752).
- Changing which validators the runner routes by file type.
- Changing `OVERSEER_CEILING` or the protected-surface rules.

## Sequencing

An unpushed local branch for **#1752** edits the same aggregation block and adds
`failed_validators` / `skipped_validators` to summary.json. This work MUST NOT depend
on it; whichever merges second rebases and reconciles field names so one classification
list exists, not two. Architect should name the reconciled field set.

## Escalations (human decisions required)

- **ESC-1 — Merge-authority response to a not-scored PR (blocks REQ-1717-13 merge
  rows).** The effective baseline tier is max(baseline, `tier_floor`); the candidate
  baselines are MEDIUM / HIGH / CRITICAL:
  (MEDIUM) **Recommended:** a green deletion-only docs PR stays within ceiling HIGH and
      can auto-merge, with not-scored disclosed. Mirrors the panel's AD-6 MEDIUM clamp;
      MEDIUM triggers agy second review (REQ-W-08), one independent read of a change no
      validator measured. Cost: one agy call per deletion-only docs PR.
  (HIGH) Auto-merge still possible at ceiling HIGH, but codex second review also fires.
  (CRITICAL) Always HUMAN_REQUIRED with an honest "not scored" reason. Fixes the
      misreport but keeps the friction.
  Excluded: any rule that can yield LOW (e.g. a structural estimate via
  `require_tier_ceiling._simplified_tier`). That is the "silent LOW" the issue warns against.
- **ESC-2 — Is "not scored" a legitimate steady state for deletion-only docs diffs, or
  a coverage gap?** Recommendation: legitimate steady state for deletion-only docs
  diffs; no docs dimension needed for this case (see Non-goals).
- **ESC-3 — Mixed N/A + Errored with zero weighted scores.** REQ-1717-03 keeps it
  CRITICAL (conservative). Confirm, or rule that it should be not-scored-with-error.
  Recommendation: keep CRITICAL — an Errored weighted dimension is unreadable, not N/A.
