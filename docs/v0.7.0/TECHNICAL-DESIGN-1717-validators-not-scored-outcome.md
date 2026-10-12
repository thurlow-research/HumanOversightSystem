# TECHNICAL-DESIGN-1717 — Validators "not scored" outcome

Issue: #1717 (v0.7.0). Author: technical-design. Date: 2026-10-12. Round: 9. The agy round-3 findings are applied, marked `[agy3-1/2]`. The §2.4 fail-closed reasons now use stable `FC_*` codes, and the body and tests cite those codes, not position numbers. Position numbers inside the verbatim review sections refer to earlier rounds. Security-reviewer round 2 APPROVED; its advisories are applied, marked `[SEC-N1..N3]`. Architect round 4 (`[SEC-M1]`) is in the body. Code-reviewer round 2 APPROVED (TD HEAD 53665ee65); its four SHOULD_FIX items are applied, marked `[CR2-1..4]`. Architect round 2 APPROVED WITH CONDITIONS, with C-5 and C-6 folded in (marked `[C-5]`, `[C-6]`) and AQ-4 accepted. Architect APPROVED WITH CONDITIONS in round 1; C-1..C-4 and the four agy second-review findings are folded into the body (each change is marked `[C-n]` or `[agy-n]`). Round 3 applies code-reviewer M-1 and S-1..S-3 (marked `[CR-M1]`, `[CR-S1..S3]`). `[CR-S1]` is a proposed D6 tightening that awaits an architect ruling (AQ-4). The architect's review is kept verbatim at the end.
Inputs (binding): `REQUIREMENTS-1717-validators-not-scored-tier.md`, `ADR-1717-validators-not-scored-outcome.md` (D1–D9) `[CR3-5]`.
Scope: **S1a coder-ready**. S1b/S2/S3/S4 outlined only (§9).

RISK: MEDIUM. CONFIDENCE: HIGH on the S1a contracts (the architect ruled on pin-test placement in AQ-1).
Change classification: **additive**. This is a new document that implements an accepted ADR and does not change any existing contract. The structural decision (the not-scored outcome) was made in the ADR and is human-gated through ESC-1. S1a ships the interim `CRITICAL` base, so merge behaviour is unchanged.

## Human Review Required
- ESC-1 (the value of `NOT_SCORED_BASE_TIER`) is still open and blocks S4 only. ESC-2 blocks nothing.
  - **`[SEC-N1]` Context for the ESC-1 decision-maker:** "docs" here means a `.md`/`.rst` *suffix*. That set includes instruction-bearing files that are not protected surfaces (`.claude/commands/*.md`, nested `CLAUDE.md`/`AGENTS.md`, `prompts/**`, `.github/pull_request_template.md`, runbooks).
  - A ruling below `HIGH` (option C, MEDIUM) therefore carries a binding precondition: a docs-class allowlist or deny list must land first (§9 S4).
- Nothing in S1a changes user-visible merge behaviour: every not-scored path resolves to CRITICAL until S4.

## 1. Merge-ordering constraint (load-bearing)

S1a and S1b may merge in either order or together. **S2 (the producer) MUST NOT merge before both S1a and S1b are on `main`.** The S2 PR body cites their merge SHAs. If the producer emits `NOT_SCORED` first, `require_tier_ceiling` falls back to its structural estimate (LOW), which is a fail-open. S3 can merge at any time after S1a, because it calls the helper CLI. S4 waits for the ESC-1 ruling and lands after S2.

## 2. New module `scripts/oversight/validator_outcome.py` (S1a)

Stdlib only. It MUST NOT import anything from `scripts/oversight/validators/`: `require_tier_ceiling` is a trusted-base gate, and the validators mutate `sys.path` when imported (`require_tier_ceiling.py:143-146`). Callers pass the weights in as an argument. Executable, with a `#!/usr/bin/env python3` header and a docstring.

### 2.1 Constants
| Name | Value | Notes |
|---|---|---|
| `NOT_APPLICABLE_ERROR` | `"no input files"` | D2. The only N/A signal |
| `NOT_SCORED` | `"NOT_SCORED"` | D1 sentinel tier |
| `TIERS` | `("LOW","MEDIUM","HIGH","CRITICAL")` | ordered; rank = index |
| `NOT_SCORED_BASE_TIER` | `"CRITICAL"` | D7 interim (option A). The single ESC-1 decision point; S4 flips it. On import, assert it is in `TIERS` |
| `OUTCOME_SCORED`, `OUTCOME_NOT_APPLICABLE`, `OUTCOME_ERRORED`, `OUTCOME_SKIPPED` | `"scored"`, `"not_applicable"`, `"errored"`, `"skipped"` | per-validator outcomes |
| `RUN_SCORED`, `RUN_NOT_SCORED`, `RUN_FAIL_CLOSED` | `"scored"`, `"not_scored"`, `"fail_closed"` | `scoring_outcome` values |

### 2.1a Path facts `[SEC-M1]` (architect round 4)
| Name | Value |
|---|---|
| `PATH_PRESENT`, `PATH_DELETED_DOCS`, `PATH_DELETED_OTHER`, `PATH_UNRESOLVED` | `"present"`, `"deleted_docs"`, `"deleted_other"`, `"unresolved"` |
| `DOCS_CLASS_SUFFIXES` | `(".md", ".rst")`. Compared exactly, case-sensitive, on the final suffix. `.txt` is excluded on purpose, because `requirements*.txt` are manifests |

`classify_path(path: str, *, exists: bool, deleted: bool, protected: bool) -> str` is pure and total:
- `exists` → present. A path that is both deleted and present is present (for example a delete and re-add).
- `deleted` and not `protected` and the suffix is in `DOCS_CLASS_SUFFIXES` → deleted_docs.
- `deleted` otherwise → deleted_other.
- anything else → unresolved.

The helper does no I/O and no glob matching here. The S2 runner supplies `exists`, `deleted` and `protected` (§9).

### 2.2 `classify(result: object) -> str` (one validator outfile → outcome)
It is total and never raises. "Usable score" means `isinstance(score,(int,float))`, not `bool`, finite, and `0 <= score <= 1`.

| # | Input | Outcome |
|---|---|---|
| 1 | not a `dict` (a list, `None`, a str or a number) | errored |
| 2 | `result.get("error") == NOT_APPLICABLE_ERROR` and the value is a `str` (exact; no strip or case-fold) | not_applicable |
| 3 | `"error"` absent or `None`, and the score is usable | scored |
| 4 | `"error"` absent or `None`, and the score is missing or unusable | errored |
| 5 | any other `error` value: another string (including `""`, `"No input files"`, `"no input files "`), `False`, `0`, a list | errored |

`skipped` is never returned by `classify()`. It applies only to names passed in `skipped_names` (D3: the script is absent, so there is no outfile).

### 2.3 `is_weighted(result: dict, weights: Mapping[str, float]) -> bool` (D6)
Choose the source: `result["weight"]` if the key exists. Otherwise, if `result.get("dimension")` is a `str` that is in `weights`, use `weights[dimension]`. Otherwise the weight is unknown.
If the key exists but its value is invalid, the weight is unknown. Do **not** fall back to `weights`.
Value rule: numeric (not `bool`), finite and `> 0` → `True`. Exactly `0`/`0.0` → `False`. Anything else (negative, NaN, a non-numeric value, unknown) → `True`, which is conservative.

### 2.4 `decide_zero_weight_outcome(results: Sequence[object], weights: Mapping[str, float], skipped_names: Sequence[str] = (), *, path_facts: Mapping[str, str] | None) -> RunDecision` `[SEC-M1]`
`path_facts` is keyword-only and has **no default**, so every caller must state it. It maps each changed path to one `PATH_*` kind (§2.1a). `None` or an empty mapping means there is no proof about the paths, so the run is `fail_closed`.
`RunDecision` is a frozen dataclass with these fields: `outcome: str` (`RUN_NOT_SCORED` | `RUN_FAIL_CLOSED`), `validator_outcomes: dict[str, str]`, `reason: str`, `reason_code: str` (`[agy3-1]`; one of the `FC_*` codes below, or `"ok"`), `not_applicable_weighted: tuple[str, ...]` (sorted).

Contract precondition, documented for S2: call it **only** inside the legacy fail-closed branch (`total_w == 0 or not successful`, `run_validators.sh:468`). Runs that take the scored path never consult it, which is what keeps REQ-04 byte-identical.

Naming `[agy-2]`: compute `dim = result.get("dimension") if isinstance(result, dict) else None`. The key is `dim` iff `isinstance(dim, str) and dim`; otherwise it is `f"<result-{i}>"`. Never index with `result["dimension"]`: a non-dict result, or one with no dimension, must not raise `KeyError`, `TypeError` or `AttributeError`. The same safe extraction applies wherever §2.3/§2.4 read `dimension`. A duplicate key gets a `#2`, `#3`, … suffix. Each skipped name maps to `"skipped"`. If a skipped name collides with a result key, the result keeps its key and the skipped entry gets the next suffix.

`RUN_NOT_SCORED` requires **all** of the following (D6). Any failure gives `RUN_FAIL_CLOSED`:
1. `len(results) >= 1`;
2. no result is both `scored` and `is_weighted`;
3. no result is `errored`, whatever its weight;
4. at least one result is both `not_applicable` and `is_weighted`;
5. **`[CR-S1]` accepted by the architect (AQ-4, round 2; ADR D6 amended):** `skipped_names` is empty.
   - Any skipped validator (no outfile because the script is absent, `run_validators.sh:222-225`) forces `fail_closed`.
   - Why: D4 assumes that losing `diff_size` cannot quietly drop the floor. A skipped `diff_size` (weight 0, floor-bearing) or a skipped weighted validator produces no outfile, so neither condition 3 nor `tier_floor` hoisting can see it.
   - I chose "any skipped" rather than "skipped weighted-or-floor-bearing". The runner's names do not match `WEIGHTS` keys (for example `complexity` vs `cyclomatic`), and there is no registry of which dimensions bear floors. A per-dimension rule would have to guess, and a script-absent validator is an install defect, not a measurement.
   - Skipped names are still recorded as `"skipped"` in `validator_outcomes` (D3).
   - If the architect rules against condition 5, delete it and restore `test_decide_skipped_names_do_not_block_and_are_recorded`.
6. **`[SEC-M1]` (architect round 4; ADR D6/D9):** `path_facts` is a non-empty mapping. **`[SEC-N2]`** Every key must be a `str`, and every value must be exactly one of the four `PATH_*` strings; any other key or value (`"deleted"`, `"PRESENT"`, `None`, `1`, a non-str key) is a catch-all `fail_closed` (`FC_INVALID_PATH_FACTS`). No value may be `PATH_UNRESOLVED`. An unresolved path is a changed path that is not in the working tree and is not a confirmed deletion: a wrong checkout, a git-quoted name, or an explicit-list path that does not exist. It is unreadable evidence, so it is treated like errored. `[CR3-4]` This reconciles with the REQ definition ("an unresolved path is Errored, never N/A"): the error is recorded at **run level**. A validator whose argv paths were all unresolved still classifies as `not_applicable` in `validator_outcomes`, because its self-report really was "no input files". The **run**, however, is `fail_closed` with `FC_UNRESOLVED`, which names the paths. So an unresolved path can never produce `not_scored` (REQ-1717-21), and no per-validator outcome is rewritten.
7. **`[SEC-M1]`:** every value in `path_facts` is `PATH_DELETED_DOCS`.
   - The weighted validators report N/A **only** when none of their argv paths exist (`migration_scorer.py:184`, `issue_query.py:240`, `ip_check.py:516`). So in the zero-weight branch the only legitimate shape is a deletion-only diff.
   - A `PATH_PRESENT` path here is an anomaly: a present file should have scored.
   - A `PATH_DELETED_OTHER` path (code, config, workflows, tests, or any protected surface) is a deletion no validator measures. Under a lowered ESC-1 base, that deletion would gain a lower tier, so it stays `fail_closed`.

Reason strings (exact formats; these are tested):
- not_scored `[SEC-M1]`: `f"no weighted dimension applied: deletion-only docs diff ({n} path(s)); not applicable: " + ", ".join(sorted(na_weighted))`
- fail_closed: the first match wins, in this order. `[agy3-1]` **This is the final order.** Each reason has a stable code, which is exported as a module constant and stored in the new `RunDecision.reason_code: str` field (`"ok"` on not_scored). Tests and S2 cite the **codes**, never position numbers, so a later reorder cannot silently invalidate a reference.

  | # | Code | Reason string | Failed D6 condition |
  |---|---|---|---|
  | 1 | `FC_NO_RESULTS` | `"no validator results"` | 1 |
  | 2 | `FC_NO_PATH_FACTS` | `"no path facts"` (`None`, empty, or not a `Mapping`) `[SEC-M1]` | 6 |
  | 3 | `FC_INVALID_PATH_FACTS` | `"invalid path facts (unknown kind or non-string path): " + _paths(bad)`. `bad` holds each offending key: the key if it is a `str`, else `repr(key)`. This is the catch-all `[SEC-N2]` | 6 |
  | 4 | `FC_UNRESOLVED` | `"unresolved changed paths (not in working tree, not a deletion): " + _paths(unresolved)` `[SEC-M1]` | 6 |
  | 5 | `FC_ERRORED` | `"errored: " + ", ".join(sorted(errored))` | 3 |
  | 6 | `FC_SKIPPED` | `"skipped: " + ", ".join(sorted(skipped_names))` `[CR-S1]` | 5 |
  | 7 | `FC_ZERO_TOTAL_WEIGHT` | `"weighted dimension scored but total weight was zero: " + ", ".join(sorted(scored_weighted))` `[agy-4]` | 2 |
  | 8 | `FC_PRESENT` | `"changed paths present but no weighted dimension scored: " + _paths(present)` `[SEC-M1]` | 7 |
  | 9 | `FC_DELETED_OTHER` | `"deletion-only diff touches non-docs or protected paths: " + _paths(deleted_other)` `[SEC-M1]` | 7 |
  | 10 | `FC_NO_WEIGHTED_NA` | `"no weighted dimension was not applicable"` | 4 |

  `scored_weighted` = the keys of results that are both `scored` and `is_weighted`.

  Why this order:
  - **Evidence-quality failures** (rows 1-6) come first, because they say the inputs are unreadable.
  - Then the weight anomaly (row 7).
  - Then **path shape** (rows 8-9), which is the accurate cause whenever the diff is not a pure docs deletion.
  - `FC_NO_WEIGHTED_NA` comes **last**. `[agy3-1]` The weighted validators report N/A only when none of their argv paths exist. So a diff with present paths usually has an empty `na_weighted`, and with `FC_NO_WEIGHTED_NA` ahead of it `FC_PRESENT` was unreachable in practice. The same held for a non-docs deletion routed to no weighted validator.
  - `[agy2-2]` holds: `FC_DELETED_OTHER` is reached only after `FC_UNRESOLVED` and `FC_PRESENT` are excluded. Every path is then `deleted_docs` or `deleted_other`, so "deletion-only" is literally true.

  **Reachability (self-consistency pass, round 9).**
  - Every code is reachable with a minimal fixture:
    - `FC_PRESENT`: one present path, weight-0 results only;
    - `FC_DELETED_OTHER`: a deleted `.py` with weighted N/A;
    - `FC_NO_WEIGHTED_NA`: all `deleted_docs`, with only weight-0 results.
  - Each D6 condition 1-7 maps to at least one code, so first-match is total. When no code matches, the run is `not_scored` with `reason_code == "ok"`.
  - None of the three outcome-changing items (`FC_PRESENT`, `FC_DELETED_OTHER`, `FC_NO_WEIGHTED_NA`) can mask a lower-numbered evidence failure.
- `_paths(xs)` = the sorted paths, each rendered with `json.dumps(path, ensure_ascii=True)` so control characters cannot reach the console. The list is capped at 20, then `f" (+{k} more)"`.

### 2.5 Summary readers
- `LEGACY_TIER_KEYS = ("tier", "risk_tier", "Tier")` `[CR-S2]`. These are the keys `require_tier_ceiling._try_validator_summary` reads (`:169`). No other S1a reader reads `risk_tier` or `Tier`. Sentinel *detection* scans all three; *validation* and `effective_tier` use `tier` only. A sentinel found under `risk_tier`/`Tier` therefore routes to the helper and then fails validation → `CRITICAL`.
- `needs_helper(summary: object) -> bool` `[CR-M1]` is the **routing predicate every S1a reader uses**. It is `True` iff any of these hold:
  1. `summary` is not a `dict` `[CR-S3]`;
  2. any `LEGACY_TIER_KEYS` value is a `str` with `.upper() == NOT_SCORED` `[C-3, CR-S2]`;
  3. the `"scoring_outcome"` key is present and its value is not exactly the string `"scored"`. That covers `"not_scored"`, `"fail_closed"`, a bogus string, `None`, or a non-string.

  A legacy summary (no `scoring_outcome`, real tier), or an S2 summary with `scoring_outcome: "scored"`, returns `False` and keeps the reader's byte-identical legacy path.
- `check_consistency(summary: object) -> str | None` `[CR-M1]` returns `None` iff the summary is internally consistent for its derived outcome, else the first reason:
  - not a dict;
  - a sentinel found under `risk_tier` or `Tier` while `tier` is not the sentinel (`"sentinel under non-canonical key"`). `[agy2-1]` This check comes **second**, before `derive_scoring_outcome`. Otherwise a summary with `tier` absent and the sentinel only under `risk_tier`/`Tier` would derive `None` and report `"unrecognised scoring_outcome or tier"`, and the specified reason would be unreachable. The effective tier is CRITICAL either way;
  - `derive_scoring_outcome` is `None` (`"unrecognised scoring_outcome or tier"`);
  - `scored` and `tier` not exactly in `TIERS`;
  - `fail_closed` and `tier != "CRITICAL"`;
  - `not_scored` and `validate_not_scored(...)` returns an error (that error is returned).
- `derive_scoring_outcome(summary: object) -> str | None`
  - A `scoring_outcome` key is present: return it if it is one of the three RUN_ values, else `None`.
  - The key is absent (legacy): `tier == NOT_SCORED` → `not_scored`. `tier == "CRITICAL"` with a non-empty `str` top-level `error` (the legacy marker, `:476`) → `fail_closed`. `[agy3-2]` Every other exact `TIERS` value → `scored`. That **includes** `"CRITICAL"` with no top-level `error`, or with an `error` that is not a non-empty `str` (a legacy scored run whose composite was ≥ 0.78). It also includes `"LOW"`, `"MEDIUM"` and `"HIGH"`, whatever `error` holds. Anything else → `None`.
- `is_not_scored(summary: object) -> bool` `[C-5]` (this is the single definition): `True` iff `isinstance(summary, dict)` and (**any** `v` in `(summary.get(k) for k in LEGACY_TIER_KEYS)` satisfies `isinstance(v, str) and v.upper() == NOT_SCORED`, **or** `summary.get("scoring_outcome") == RUN_NOT_SCORED`).
  - Detection uses the legacy readers' own `.upper()` normalisation `[C-3]`. `validate_not_scored` stays **exact**, so any non-canonical spelling or key resolves to `CRITICAL`. N/A error text (`classify` row 2) stays exact under REQ-01.
  - Readers route on `needs_helper`, not on this predicate `[CR-M1]`. `is_not_scored` only selects the not-scored display and validation sub-path inside the helper branch.
- `validate_not_scored(summary: object) -> str | None`: returns `None` if the summary is a well-formed not-scored summary, else the **first** failing reason, in this order:
  1. not a dict;
  2. `tier != NOT_SCORED`;
  3. the `composite_score` key is missing, or its value is not `None`;
  4. `scoring_outcome` is present and `!= RUN_NOT_SCORED`;
  5. `not_scored_reason` is not a non-empty `str`;
  6. `validator_outcomes` is not a `dict` of `str` to one of the four outcomes;
  7. `tier_floor` is present, not `None`, and not in `TIERS`.
- `effective_tier(summary: object) -> str` (D7). It is total, never raises, and always returns a member of `TIERS`. Rules are evaluated in order:
  1. `check_consistency` returns an error → `CRITICAL`. This covers a non-dict, unknown outcome or tier, `"SAFE"`, `"low"`, a non-canonical sentinel, and `{"tier":"LOW","scoring_outcome":"fail_closed"}`.
  2. Outcome is `fail_closed` → `CRITICAL` `[C-4]`.
  3. Outcome is `not_scored` → `max_by_rank(NOT_SCORED_BASE_TIER, tier_floor or NOT_SCORED_BASE_TIER)`.
  4. Outcome is `scored` → `tier` unchanged. **No floor folding.**
  - `[CR2-4]` This is an intentional, conservative divergence. The helper requires the exact uppercase tier, so a lowercase tier (for example `"low"`) on a summary routed to the helper is `CRITICAL`. The legacy `require_tier_ceiling` path upper-cases a tier on a non-routed summary (`:170-171`, kept by `[CR2-1]`). The producer only writes uppercase tiers, so this only affects malformed input.

### 2.6 CLI (`main(argv: list[str] | None = None) -> int`; argparse with subcommands)
- `effective-tier <summary.json>`: prints exactly one `TIERS` word and a newline to stdout.
  - Exit 0 when the file parsed as JSON. A malformed dict, or a non-dict, prints `CRITICAL`.
  - Exit 3 when the file is missing, unreadable or not JSON. It still prints `CRITICAL`, and writes one stderr line naming the cause. Callers choose whether a missing summary is fatal.
- `describe <summary.json>`: prints one JSON object `{"scoring_outcome", "effective_tier", "not_scored_reason", "tier_floor", "validation_error"}`, using `null` where a value is absent. The exit codes are the same as for `effective-tier`. This is for S3 agent prose.
- A usage error exits 2 (the argparse default). The script header documents exits 0, 2 and 3.

## 3. Reader changes (S1a). Each reader consults the helper **only** when `needs_helper()` is true `[CR-M1]`; legitimate values keep byte-identical handling

`[CR2-2]` Legitimate summaries are handled byte-identically:
- a real tier in LOW..CRITICAL, with no `scoring_outcome` or with `scoring_outcome: "scored"`;
- an absent summary file.

Malformed or unknown values in a **present** summary are *not* treated as before. A non-dict, an unparseable file, or an unknown, missing or non-canonical tier now resolves to CRITICAL or the reader's fail-safe (`[CR-S3]`, `[C-6]`), where previously some fell back to a weaker estimate.

`[CR-M1]` In round 2, routing was on `is_not_scored`. That left `{"tier":"LOW","scoring_outcome":"fail_closed"}` and bogus outcomes on the legacy path, where they read as LOW, which is a fail-open. Every reader below now routes on `needs_helper`.
- A legitimate S2 `fail_closed` summary (`tier` CRITICAL, composite 1.0) also enters the helper branch. Its effective tier is `CRITICAL`, which is the same value its legacy path gives, so reader *verdicts* are unchanged. The only additions are the diagnostic fields noted per reader.
- Legacy summaries without `scoring_outcome`, and `scoring_outcome: "scored"` summaries, never enter the helper branch.

### 3.1 `scripts/framework/require_tier_ceiling.py` (closes the one fail-open)
- Add a private `_load_validator_outcome()`, cached with `functools.cache`. It loads `Path(__file__).resolve().parents[1] / "oversight" / "validator_outcome.py"` through `importlib.util.spec_from_file_location`. It is lazy, so the CI path (no summary) never loads it.
- In `_try_validator_summary` (`:162-174`), right after `json.loads` (`:168`): if `vo.needs_helper(data)` `[CR-M1]`, return `vo.effective_tier(data)`. If the load or the call fails, return `"CRITICAL"`. A failure here must never reach `None`, because `None` means structural fallback.
- `[CR-S3]` **File present but unusable → `"CRITICAL"`.** Today, a `summary.json` that exists but is unreadable, is not JSON, or parses to a non-dict hits `except Exception: return None` (`:172-173`) or a non-dict `.get` failure, so it falls back to the structural estimate (possibly LOW).
  - New rule: once `summary.is_file()` is true (`:165`), every read or parse failure and every non-dict returns `"CRITICAL"`. A non-dict goes through `needs_helper` → `effective_tier`; read and JSON errors return the literal directly, without loading the helper.
  - Byte-identity: the producer always writes a dict through `json.dumps` (`run_validators.sh:480`, `:518`), so no real scored path is affected. The CI path (no file, `:165-166`) still returns `None`.
- `[C-6]` **Present summary with an unknown or missing tier → `"CRITICAL"`.**
  - This applies once `summary.is_file()` is true and the dict did **not** route through the helper (`needs_helper` is False).
  - `[CR2-1]` Validate the **legacy-selected** value, not "any value". That is `selected = data.get("tier") or data.get("risk_tier") or data.get("Tier")` (`:169`): the first truthy value, which is the legacy reader's own selection.
    - If `selected` is a `str` and `selected.upper()` is in `("LOW","MEDIUM","HIGH","CRITICAL")`, return `selected.upper()`, exactly as today (`:170-171`).
    - Otherwise return `"CRITICAL"`. That covers no truthy key, `"bogus"`, `3`, and `"SAFE"` (AQ-5).
    - So `{"tier":"bogus","Tier":"LOW"}` is CRITICAL: the selected value is `"bogus"`, and a valid later key does not rescue it. `{"tier":"","Tier":"LOW"}` still selects `"LOW"`, as today.
  - This also covers `scoring_outcome:"scored"` with an unknown tier, because `needs_helper` is False there.
  - An absent file still returns `None` (the CI path, unchanged). This replaces round 3's "unknown non-sentinel tier still returns None" exception, which the architect overruled in round 2.
- `compute_tier` (`:304-306`) still takes `_max_tier(tier, structural)`. `require_overseer_approval.py` inherits through `compute_tier_for_pr` (`:348`) and needs no edit.

### 3.2 `scripts/oversight/release_artifact_logic.py`
- Add a lazy path-loader `_load_validator_outcome()` in the style of `_load_audit_log` (`:267-280`). `[CR2-3]` The helper is needed for **every** artifact, both to evaluate `needs_helper()` and to process any artifact it routes. If the load fails, or any helper call raises, on any artifact, record `parse_error` = `"validator_outcome helper unavailable: <exc>"`. That is an escalation, so it fails closed. It is never treated as a legacy or scored artifact.
- `StepArtifactInfo` (`:95-105`):
  - change to `composite_score: float | None = 0.0`;
  - add `effective_tier: str = ""`, `scoring_outcome: str = "scored"` and `not_scored_reason: str = ""`.
- `check_artifact_integrity` (`:148-162`): after the required-field loop (`:154-156`), if `vo.is_not_scored(artifact)` → `return vo.validate_not_scored(artifact)`, prefixed `"not-scored artifact invalid: "` when not `None`. Otherwise the existing numeric checks run unchanged (`:157-162`). `[CR-S3]` Add a first guard: `if not isinstance(artifact, dict): return "artifact is not a JSON object"`.
  - Today a JSON list falls into the required-field loop and returns "missing required field".
  - A JSON number or `null` makes `f not in artifact` raise `TypeError` (`:155`). That error escapes `_load_step_artifact` and breaks the "never raises" contract (`:316`).
  - Dict artifacts are unaffected.
- `_load_step_artifact` (`:212-220`):
  - not-scored: `tier="NOT_SCORED"`, `composite_score=None`, `effective_tier=vo.effective_tier(artifact)`, `scoring_outcome="not_scored"`, `not_scored_reason=...`;
  - `[CR-M1]` other `needs_helper` artifacts (a numeric composite has passed integrity):
    - `tier` = the recorded value upper-cased, as today; `composite_score` = the float, as today;
    - `effective_tier = vo.effective_tier(artifact)`, which is `CRITICAL` for `fail_closed`, inconsistent or bogus outcomes;
    - `scoring_outcome` = the raw value coerced with `str()`;
    - if `vo.check_consistency(artifact)` returns an error, append a warning `f"step {id}: summary inconsistent ({err}); treated as CRITICAL"`;
  - otherwise: `effective_tier = tier`, with the existing fields unchanged.
- `[CR-M1]` The tier column and the audit event carry `effective_tier` for every `needs_helper` artifact, not only not-scored ones.
- Sweep (`:351-366`) tests `info.effective_tier in HIGH_PLUS_TIERS`. For scored artifacts this is the same value as today.
  - Not-scored with blocking findings, escalation text: `f"step {id}: not scored (effective tier {eff}) with {n} unresolved blocking finding(s) — human authorization required"`.
  - Not-scored without blocking findings, warning text: `f"step {id}: not scored (effective tier {eff}; {reason}; no blocking findings — approved)"`. This never formats `None` with `:.3f`.
- `to_audit_event` (`:131-134`): a `needs_helper` entry `[CR-M1]` adds `"effective_tier"` and `"scoring_outcome"`. Legacy and `scored` entries keep exactly `{"step","tier","path"}`.
- CLI summary print (`:521-530`) `[C-1]`: for a not-scored `info`, the tier column prints `info.effective_tier` (not `NOT_SCORED`), with the same RED/YELLOW colouring rule, and `score=…` is replaced by `not scored → <effective_tier>`. Scored steps print byte-identically. Without this, `f"{None:.3f}"` raises `TypeError` during `cut_release.sh`, because under the interim base every not-scored step is in `high_plus_steps`.
- Audit rule `[C-1]`: the only `composite_score` formatting sites today are `:365` (sweep warning) and `:528` (CLI print), and `:217` is the `float(...)` conversion. All three branch on `scoring_outcome == "not_scored"` before touching `composite_score`. The coder re-greps `composite_score` in the file before PR, and every site must tolerate `None` on a not-scored info.
- `cut_release.sh` inherits these changes and needs no edit.

### 3.3 `scripts/automation/lib/pr_readiness.py` REQ-W-03 (`_check_validators_current`, `:373-403`)
- Import `from scripts.oversight.validator_outcome import needs_helper, is_not_scored, validate_not_scored, check_consistency, effective_tier`. This follows the package convention at `:68-70` and the precedent in `scripts/oversight/record_agent_model.py:41`.
- Committed branch (`:375-390`): before the `composite is None` test (`:378`), if `is_not_scored(committed)`:
  - `err = validate_not_scored(committed)`. If there is an error → fail with `f"{path} not-scored summary invalid: {err}"`.
  - Then apply the **same** head_sha stale check (`:382-387`).
  - Pass message: `f"validators current (head_sha matches, not scored: {reason}; effective tier {effective_tier(committed)})"`.
- Ephemeral fallback (`:392-403`): before calling `load_composite_score`, read `_read_json(repo_root / _SUMMARY_PATH)`. If it `is_not_scored`, validate it as above and pass with `f"validators ran (not scored: {reason}; effective tier {eff}); no committed summary yet to stamp-check head_sha"`.
- `[CR-M1]` Gap check:
  - REQ-W-03 is a freshness check and never reads `tier`, so a LOW-as-fail_closed summary cannot pass it *as LOW*. But it would pass as "current" while being internally contradictory.
  - So for both branches: if `needs_helper(summary)` and not `is_not_scored(summary)`, and `check_consistency(summary)` returns an error → fail with `f"{path} summary inconsistent: {err}"`.
  - `[agy2-3]` Guard: all helper checks in §3.3 (`is_not_scored`, `validate_not_scored`, `needs_helper`, `check_consistency`) run **only when the `_read_json` result is not `None`**.
    - `_read_json` returns `None` for an absent, unparseable or non-dict file (`:196-205`).
    - In the committed branch this already holds, because everything sits inside `if committed is not None:` (`:375`).
    - In the ephemeral fallback, a `None` read skips the helper and falls through to the existing `load_composite_score` path and its existing message (`:392-398`). Otherwise `needs_helper(None)` → True and `check_consistency(None)` → `"not a dict"` would replace the existing missing-summary failure.
  - A consistent `fail_closed` summary (CRITICAL, numeric composite) keeps today's pass text exactly.
- A `null` composite *without* the sentinel keeps today's failure text. REQ-W-08 (tier from `--risk-tier`) is unchanged. S3 makes agents pass the helper's effective tier.

### 3.4 `scripts/oversight/second_review_logic.py` digests (`:974-1025`)
- Add a lazy path-loader for the sibling helper.
- In `_digest_tier1` and `_digest_tier3`, **only** when `vo.needs_helper(summary)` `[CR-M1]`, add these keys after `tier`: `"scoring_outcome"` and `"effective_tier"`. When `vo.is_not_scored(summary)` is also true, add `"not_scored_reason"`, `"validator_outcomes"` and `"tier_floor"` as well.
  - Gap check: today the digest only passes `tier` through, so an inconsistent summary would show the reviewer `LOW`. With this change the reviewer also sees `effective_tier: CRITICAL`.
  - Reviewer *selection* is S1b, and it must route on `needs_helper` too (§9).
  - A legitimate S2 `fail_closed` digest gains these two keys. The scored digest is unchanged.
- `_digest_tier2` inherits through its deep copy (`:1006`). `composite_score` passes through as `null`.
- A scored summary produces a byte-identical digest: no new keys, because a scored run's `scoring_outcome` (added in S2) is not copied.
- If the helper fails to load, an exception propagates to `_cmd_digest_validators` (`:1219+`), whose existing guard degrades with a stderr line and exit 0. That is acceptable: the digest is informational, and reviewer selection belongs to S1b.

### 3.5 `scripts/automation/lib/gate_compliance.py`: no code change
`load_composite_score` (`:58-73`) returns `None` for `null`, and NN-17 (`:173`) skips `None`. The REQ-13 row is satisfied by a test only.

### 3.6 `scripts/oversight/signoff_gate.py`: verified no dependency; no code change `[agy-1]`
This is REQ-1717-13's verify-and-record row. Verified 2026-10-12 against the 493-line file:
- Imports (`:46-53`) are `argparse`, `os`, `re`, `subprocess`, `sys` and `pathlib` only. There is no `json`, so it cannot parse `summary.json`.
- `grep -n -i "tier\|composite\|summary.json"` matches only the comment at `:113` and `RESERVED_SIGNOFF_SUBDIRS = {"validators"}` at `:114`.
- That set is used solely to **skip** `signoffs/validators/` when enumerating stamp namespaces (`namespaced_stamp_rels`, `:228-242`; already covered by `tests/oversight/test_signoff_gate.py:78`).
- The gate reads only `.stamp` `status:` lines (`parse_stamp_status`, `:192`) and git commit times (`commit_time`, `:163`).

Result: a not-scored artifact cannot change its verdict. One pin test, placed in `test_validator_outcome.py` so the file count stays the same, keeps this from silently regressing (§5).

## 4. Error-handling rule (applies to every S1a reader)
- An unaware or malformed input never yields LOW, never raises out of a gate entry point, and never maps to `None` where `None` means "fall back to a weaker estimate".
- Every failure resolves to that reader's existing fail-safe:
  - require_tier_ceiling → `CRITICAL`;
  - release → `parse_error` escalation;
  - pr_readiness → REQ-W-03 fail;
  - digest → the existing degraded-digest path.
- `[CR-S3]` A present-but-unusable summary file (unreadable, not JSON, or a non-dict) is CRITICAL in `require_tier_ceiling` and a `parse_error` escalation in release. Only an *absent* file still returns `None` in `require_tier_ceiling`; that is the CI path and is unchanged.
- `[C-6]` A present dict summary with an unknown or missing tier is `CRITICAL` in `require_tier_ceiling` (§3.1). There is no accepted exception: the only `None` path left is an absent file.

## 5. Test plan (S1a). The REQ ids are the requirement ids from REQUIREMENTS-1717

**`tests/oversight/test_validator_outcome.py` (new).** Load the module with `tests.conftest.load_module_from_path`.

| Test | Asserts | REQ / ADR |
|---|---|---|
| `test_classify_exact_no_input_files_is_na` | row 2 | 01 |
| `test_classify_near_miss_strings_are_errored` (param: `"No input files"`, `"no input files "`, `" no input files"`, `"no input file"`, `"no input files."`, `"no input"`) | errored | 01, 18 |
| `test_classify_migration_unparseable_is_errored` | `"all migration files unparseable"` → errored | 18 |
| `test_classify_exhausted_retries_is_errored` | the shell envelope from `:256` → errored | D3 |
| `test_classify_non_dict_is_errored` (param: list, `None`, str, int) | errored | 01 |
| `test_classify_scored_error_none_or_absent` | row 3 | 01 |
| `test_classify_unusable_score_is_errored` (param: missing, `"0.1"`, `True`, NaN, -0.1, 1.5) | row 4 | 01 |
| `test_classify_falsy_non_none_error_is_errored` (param: `""`, `False`, `0`, `[]`) | row 5 | 01 |
| `test_is_weighted_table` (param over §2.3: 0.12, 0, absent with diff_size→0, unknown dim, `"0"`, `True`, -1, NaN, non-str dimension) | each row | D6 |
| `test_decide_docs_deletion_only_is_not_scored` `[SEC-M1]` (fixture: historical_density/ip_check/migration_risk N/A + diff_size scored, weight 0; `path_facts` all `deleted_docs`) | `not_scored`, exact reason, sorted names | 02, 15 |
| `test_decide_path_facts_none_or_empty_fail_closed` `[SEC-M1]` | `FC_NO_PATH_FACTS` | D9 |
| `test_decide_unresolved_path_fail_closed` `[SEC-M1]` (param: one unresolved among deleted_docs; all unresolved; a quoted name `"\\303\\251.py"`) | `FC_UNRESOLVED`; ranked before `FC_ERRORED` | D6-6, D9 |
| `test_decide_deleted_other_fail_closed` `[SEC-M1]` (param: deleted `.py`, deleted `.github/workflows/x.yml`, deleted protected `.claude/agents/a.md`, deleted `requirements.txt`; each both with and without a weighted N/A result `[agy3-1]`) | `FC_DELETED_OTHER` | D6-7 |
| `test_decide_present_path_in_zero_weight_branch_fail_closed` `[SEC-M1]` (param: with a weighted N/A result; with **no** weighted N/A, weight-0 results only `[agy3-1]`) | `FC_PRESENT`, never `FC_NO_WEIGHTED_NA` | D6-7 |
| `test_decide_mixed_present_and_deleted_other_reports_present` `[agy2-2]` (a present `.py` plus a deleted `.py`) | `FC_PRESENT`, and the reason text does not contain `"deletion-only"` | D6-7 |
| `test_decide_paths_rendering_capped_and_escaped` `[SEC-M1]` (25 paths; a path with `\n`) | 20 shown + `(+5 more)`; no raw newline | D9 |
| `test_classify_path_table` `[SEC-M1]` (param over §2.1a: present; deleted `.md`; deleted `.MD`; deleted `.rst`; deleted `.txt`; deleted protected `.md`; neither) | each row | D9 |
| `test_decide_unknown_path_kind_fail_closed` `[SEC-N2]` (param: value `"deleted"`, `"PRESENT"`, `None`, `1`; a non-str key `5`; `path_facts` a `list`, which gives `FC_NO_PATH_FACTS`) | `FC_INVALID_PATH_FACTS` (or `FC_NO_PATH_FACTS` for a non-Mapping), never `not_scored`; ranked before `FC_UNRESOLVED` | D9 |
| `test_decide_requires_path_facts_keyword` `[SEC-M1]` (call without `path_facts` → `TypeError`) | there is no default, so it cannot silently opt out | D9 |
| `test_decide_all_errored_fail_closed` | `FC_ERRORED`, reason `errored: …` | 03, 16 |
| `test_decide_na_plus_weighted_errored_fail_closed` | `FC_ERRORED` | 03, 16, D6 |
| `test_decide_na_plus_zero_weight_errored_fail_closed` | `FC_ERRORED` (stricter than REQ) | D6 |
| `test_decide_only_zero_weight_scored_fail_closed` | `FC_NO_WEIGHTED_NA` (condition 4) | D6 |
| `test_decide_empty_results_fail_closed` | `FC_NO_RESULTS` | 03 |
| `test_decide_unknown_weight_na_counts_as_weighted` | `not_scored` | D6 |
| `test_decide_zero_weight_na_only_fail_closed` | `FC_NO_WEIGHTED_NA` (condition 4) | D6 |
| `test_decide_reason_order_table` `[agy3-1]` | Param: one minimal fixture per `FC_*` code asserts that code is reachable, plus adjacent-pair fixtures where two conditions both fail: unresolved+errored → `FC_UNRESOLVED`; errored+present → `FC_ERRORED`; skipped+deleted_other → `FC_SKIPPED`; present+no-weighted-N/A → `FC_PRESENT`; deleted_other+no-weighted-N/A → `FC_DELETED_OTHER`. Also asserts the exported `FC_*` tuple equals the §2.4 table order | `reason_code` equals the earlier row each time; the not_scored fixture gives `"ok"` | D6, D9 |
| `test_decide_any_skipped_forces_fail_closed` (param: skipped `diff_size`; skipped weighted `ip_check`; skipped unknown name) `[CR-S1]`, AQ-4 accepted, replacing round 2's `test_decide_skipped_names_do_not_block_and_are_recorded` | `FC_SKIPPED`, reason `skipped: …`; `"skipped"` still in the map | D3, D4, AQ-4 |
| `test_decide_outcome_map_total_and_valid` (incl. duplicate and missing dimension keys) | every result and skipped name keyed; values in the four-set | 06, D3 |
| `test_effective_tier_scored_unchanged_no_floor_fold` (param over the four tiers; LOW + floor HIGH → LOW) | unchanged | 04, D7 |
| `test_effective_tier_not_scored_interim_is_critical` | `CRITICAL` | D7 |
| `test_effective_tier_floor_max` (monkeypatch base=MEDIUM; floor None/LOW/MEDIUM/HIGH/CRITICAL) | `max(base, floor)` | 08, 17 |
| `test_effective_tier_bad_floor_is_critical` (param: `"high"`, `"BOGUS"`, 5) | `CRITICAL` | D4 |
| `test_effective_tier_malformed_is_critical` (param: non-dict, no tier, tier 3, `"SAFE"`, `"low"`, NOT_SCORED+numeric composite, NOT_SCORED+outcome `scored`, HIGH+outcome `not_scored`, bogus outcome, `{"tier":"LOW","scoring_outcome":"fail_closed"}` `[C-4]`, lowercase `"not_scored"` tier `[C-3]`) | `CRITICAL`, no exception | 07, 13 |
| `test_is_not_scored_detection_case_folds_tier` (param: `"NOT_SCORED"`, `"not_scored"`, `"Not_Scored"` → True; non-str tier → False; `scoring_outcome:"not_scored"` alone → True) `[C-3]` | detection normalises; `validate_not_scored` still rejects the non-canonical spellings | 07, C-3 |
| `test_decide_naming_never_raises` (results: `[None, [], {"score":0.1}, {"dimension":5}, {"dimension":""}]`) `[agy-2]` | keys `<result-0>`..`<result-4>`, no exception | 01, D6 |
| `test_decide_zero_total_weight_reason_sorted` (two weighted `scored` results given in reverse order) `[agy-4]` | `FC_ZERO_TOTAL_WEIGHT`; exact reason string with names sorted | 03 |
| `test_signoff_gate_has_no_tier_or_composite_dependency` (AST over `scripts/oversight/signoff_gate.py`: no `json` import; no string constant equal to `"tier"`, `"composite_score"` or `"summary.json"`) `[agy-1]` | §3.6 stays true | 13 |
| `test_derive_scoring_outcome_legacy` (param `[agy3-2]`: CRITICAL with no `error` → scored; CRITICAL + `error: None` / `""` / `5` → scored; CRITICAL + `error: "…"` → fail_closed; HIGH + `error: "…"` → scored; NOT_SCORED → not_scored; `"bogus"` → None) | as listed | D1 |
| `test_validate_not_scored_each_rule` (param over §2.5 rules 1-7) | expected first error, else `None` | 06 |
| `test_not_scored_base_tier_interim_pin` | `== "CRITICAL"` and in `TIERS` (S4 updates it) | D7 |
| `test_constants_pinned` | `NOT_APPLICABLE_ERROR == "no input files"`; `NOT_SCORED not in TIERS` | D1, D2 |
| `test_cli_effective_tier_exit_codes` (valid → 0; missing → 3 + CRITICAL; non-JSON → 3 + CRITICAL; no args → 2) | stdout and exit codes | 10, 13 |
| `test_cli_describe_fields` | exact key set (`validation_error` = `check_consistency` result) | 06 |
| `test_needs_helper_table` `[CR-M1, CR-S2, CR-S3]` | param → expected: legacy LOW, no outcome → F; `scoring_outcome:"scored"` + LOW → F; `"fail_closed"` + LOW → T; `"fail_closed"` + CRITICAL → T; bogus outcome → T; outcome `None` → T; outcome `1` → T; `risk_tier:"NOT_SCORED"` → T; `Tier:"not_scored"` → T; a list / `None` / `5` → T | 07, 13 |
| `test_check_consistency_table` `[CR-M1]` | param: consistent scored / fail_closed / not_scored → `None`; LOW+fail_closed, HIGH+not_scored, NOT_SCORED+scored, bogus outcome, sentinel under `risk_tier` only (both with `tier:"LOW"` and with `tier` **absent** `[agy2-1]`) → `"sentinel under non-canonical key"`; plus `effective_tier` CRITICAL for both | 07, 13 |
| `test_module_is_stdlib_only` (AST: every import is in `sys.stdlib_module_names`; nothing from `validators`) | trusted-base safe | §2 |

**`tests/oversight/test_validator_outcome_emitter_pin.py` (new; see AQ-1).** These tests scan `scripts/oversight/validators/*.py` with AST, without importing anything.
- `test_every_expected_emitter_uses_constant`: `EXPECTED_EMITTERS` is exactly the **16** files named in AQ-1 (corrected from 17 per C-2). Each has at least one `error=<str>` keyword argument equal to `NOT_APPLICABLE_ERROR`. (REQ-01, D2)
- `test_no_drifted_no_input_error_literal`: every `error=` keyword string, and every `"error":` dict-value string *inside a `make_result(...)` call*, that matches `(?i)no[\s_-]*input[\s_-]*files?` equals the constant exactly. Raw_value placeholders such as `{"error": "no input"}` are outside `make_result`'s `error=` and are excluded. (REQ-01, 18)
- `test_emitter_set_is_exact`: the set of files containing the constant `== EXPECTED_EMITTERS`, so adding a new emitter requires a deliberate manifest edit. (D2)

**Reader tests (extend the existing files).**
| File | Tests | REQ |
|---|---|---|
| `tests/framework/test_require_tier_ceiling.py` | `test_summary_not_scored_returns_effective_tier_not_none`; `test_summary_not_scored_floor_high_with_medium_base` (monkeypatch); `test_compute_tier_docs_only_not_scored_is_not_structural_low` (plus `main` → exit 1 when overseer-approved); `test_present_summary_unknown_tier_is_critical` (param: `"SAFE"`, `"bogus"`, missing key, `3`) `[C-6]`, replacing `test_unknown_non_sentinel_tier_still_none`; `test_scored_outcome_with_sentinel_tier_is_critical` `[C-6]`; `test_scored_outcome_with_unknown_tier_is_critical` `[C-6]`; `test_legacy_selected_tier_is_validated` (param: `{"tier":"bogus","Tier":"LOW"}` → CRITICAL; `{"tier":"","Tier":"LOW"}` → LOW) `[CR2-1]`; `test_helper_load_failure_is_critical`; `test_inconsistent_not_scored_is_critical`; `test_lowercase_sentinel_routes_to_helper_and_is_critical` `[C-3]`; `test_fail_closed_outcome_with_low_tier_is_critical` `[CR-M1]`; `test_bogus_scoring_outcome_is_critical` `[CR-M1]`; `test_risk_tier_key_sentinel_is_critical` `[CR-S2]`; `test_present_unusable_summary_is_critical` (param: non-JSON, JSON list, JSON number) `[CR-S3]`; `test_absent_summary_still_none` (CI-path control) `[CR-S3]` | 07, 13, 19 |
| `tests/oversight/test_release_artifact_logic.py` | `test_integrity_valid_not_scored`; `test_integrity_not_scored_numeric_composite_rejected`; `test_integrity_not_scored_missing_reason_rejected`; `test_integrity_null_composite_scored_tier_unchanged_message`; `test_sweep_not_scored_interim_warns_and_passes`; `test_sweep_not_scored_blocking_findings_escalates`; `test_sweep_not_scored_medium_base_not_high_plus` / `..._floor_high_is_high_plus` (monkeypatch); `test_audit_event_scored_entries_byte_identical`; `test_audit_event_not_scored_entry_fields`; `test_cli_summary_prints_not_scored_step_without_typeerror` `[C-1]`; `test_sweep_fail_closed_low_tier_is_critical_high_plus` `[CR-M1]`; `test_sweep_bogus_outcome_is_critical_high_plus` `[CR-M1]`; `test_sweep_consistent_fail_closed_verdict_unchanged` `[CR-M1]`; `test_helper_load_failure_any_artifact_is_parse_error` (param: legacy scored artifact; `fail_closed` artifact; not-scored artifact; helper monkeypatched to raise) `[CR2-3]`; `test_non_object_artifact_is_parse_error_not_raise` (param: list, number, `null`) `[CR-S3]` | 09, 13, 17, 19 |
| `tests/automation/test_pr_readiness.py` | `test_req_w03_committed_not_scored_passes_with_reason`; `test_req_w03_committed_not_scored_stale_head_fails`; `test_req_w03_committed_not_scored_invalid_fails`; `test_req_w03_null_composite_without_sentinel_unchanged`; `test_req_w03_ephemeral_not_scored_passes`; `test_req_w03_scored_message_byte_identical`; `test_req_w03_inconsistent_outcome_fails` (LOW+fail_closed; bogus outcome) `[CR-M1]`; `test_req_w03_consistent_fail_closed_message_unchanged` `[CR-M1]`; `test_req_w03_absent_summaries_keep_existing_message` `[agy2-3]` (no committed and no ephemeral summary → the exact existing "neither … has a composite_score" text, not "summary inconsistent"); `test_req_w03_sentinel_only_under_risk_tier_fails` `[C-6]` (the gate half is covered by `test_risk_tier_key_sentinel_is_critical`) | 13, 19 |
| `tests/oversight/test_second_review_logic.py` | `test_digest_tier1_not_scored_carries_reason_and_null_composite`; `test_digest_tier3_not_scored_carries_reason`; `test_digest_scored_byte_identical_golden`; `test_cmd_digest_validators_not_scored_exit0`; `test_digest_inconsistent_outcome_shows_effective_critical` `[CR-M1]` | 13, 19 |
| `tests/oversight/test_gate_compliance.py` | `test_nn17_not_scored_summary_does_not_trip`; `test_nn17_scored_critical_still_trips` (control) | 13, 19 |

Total: **47 helper + 3 pin + 48 reader = 98 named tests**. Round 9: `[agy3-1]` adds `test_decide_reason_order_table`; `[agy3-2]` extends an existing parametrization. Before that: (`[agy2-2]` +1 helper, `[agy2-3]` +1 pr_readiness; `[agy2-1]` extends an existing parametrization) `[CR3-1]`. These are recounted from the table rows: the helper table has 45. Round-by-round deltas below are kept for history, and earlier helper subtotals were stale.
- `[CR3-2]` **Fixture `VALID_DOCS_DELETION_FACTS`** = `{"docs/old-guide.md": PATH_DELETED_DOCS}`, a module-level constant in `test_validator_outcome.py`.
  - Every `test_decide_*` test whose subject is **not** path facts must pass `path_facts=VALID_DOCS_DELETION_FACTS`. That includes the errored, skipped, unknown-weight, zero-weight, naming, outcome-map and sorted-reason tests, among others.
  - Without it, those tests would stop at `FC_NO_PATH_FACTS` and never reach the reason they test.
  - The path-fact tests (`*_path_facts_*`, `*_unresolved_*`, `*_deleted_other_*`, `*_present_path_*`, `*_unknown_path_kind_*`, `*_requires_path_facts_*`) build their own facts.
- Round 6 adds 1: `[SEC-N2]` in the helper. The `[SEC-N2]` S2 completeness test is an S2 test and is not counted here.
- Round 5 adds 2: `[CR2-1]` in require_tier_ceiling and `[CR2-3]` in release.
- Round 4 adds 3 (`[C-6]`): two in require_tier_ceiling, plus one replacement there, and one in pr_readiness.
- Round 2 added 6 (C-1, C-3 ×2, agy-1, agy-2, agy-4); C-4 extended an existing parametrization.
- Round 3 adds 14:
  - helper +2 (`needs_helper`, `check_consistency`). `[CR-S1]` replaces a test rather than adding one.
  - require_tier_ceiling +5, release +4, pr_readiness +2, digest +1. Parametrized tests count once here.
Every reader's scored-fixture test proves REQ-04/REQ-19 unchanged. Run them with `scripts/framework/run_tests_inner_loop.sh`, and use the oversight venv (`scripts/oversight/.venv/bin/`).

## 6. S1a file list (13 ≤ 15)
1. `scripts/oversight/validator_outcome.py` (new)
2. `tests/oversight/test_validator_outcome.py` (new)
3. `tests/oversight/test_validator_outcome_emitter_pin.py` (new)
4. `scripts/framework/require_tier_ceiling.py`
5. `tests/framework/test_require_tier_ceiling.py`
6. `scripts/oversight/release_artifact_logic.py`
7. `tests/oversight/test_release_artifact_logic.py`
8. `scripts/automation/lib/pr_readiness.py`
9. `tests/automation/test_pr_readiness.py`
10. `scripts/oversight/second_review_logic.py`
11. `tests/oversight/test_second_review_logic.py`
12. `tests/oversight/test_gate_compliance.py`
13. `SCRIPTS-INDEX.md` (regenerate with `scripts/framework/regen_all.sh` for the new script; run `--check` before the PR)

Nothing else needs to be added for shipping: `scripts/oversight/` is installed by rsync (`framework_consumer_files.txt:8`), and the CI tier-ceiling job does a full trusted-base checkout (`require-tier-ceiling.yml`).

## 7. Boundaries
- S1a never writes `NOT_SCORED` anywhere. Only test fixtures contain it.
- `[CR2-2]` No reader handles a **legitimate** non-sentinel value differently than it does today. Legitimate means a real LOW..CRITICAL tier with no `scoring_outcome` or with `"scored"`, or an absent file. Malformed or unknown values in a present summary now resolve to CRITICAL or the reader's fail-safe (`[CR-S3]`, `[C-6]`, `[CR-M1]`). That is an intentional tightening, approved in architect round 2.
- `pr_readiness --risk-tier`, `pr_review_cli --tier` and `merge_authority.RiskTier.from_str` keep rejecting `NOT_SCORED` (D7).
- The helper never folds `tier_floor` into a scored tier. That stays the risk-assessor's job.

## 8. Design questions for architect
- **AQ-1: pin-test placement and the emitter count.** The ADR puts the constant-pin test in S2 and says "all 10 emitters" (Context, D2). A grep finds **19 matching lines in 16 files** (corrected from "17 files" per C-2: 16 `error=` kwargs, 2 raw_value dict literals, 1 comment): `complexity_metrics{,_js}`, `function_metrics{,_js}`, `hallucination_surface{,_js}`, `n1_detector{,_js}`, `rn_calculator{,_js}`, `static_analysis{,_js}`, `ip_check`, `prompt_audit_risk`, `issue_query`, `migration_scorer`. `ip_check` and `prompt_audit_risk` add a raw_value `{"error": ...}` literal. I place the pin test in **S1a**, because that is where the constant is defined. It is test-only and changes no behaviour, and the test pins the real set of 16. **Ruled: confirmed, with C-2.**
- **AQ-2: classification can be stricter than legacy truthiness.** `classify()` treats `error: ""` or `False`, and a non-numeric score, as *errored*. The legacy composite (`:459`, `if r.get("error")`) treats them as successes. This only decides outcomes inside the legacy fail-closed branch (§2.4 precondition). But on a scored run, S2's `validator_outcomes` could label a result "errored" that the composite included. My proposal is to accept that, since it is conservative and REQ-04 still holds, and have S2 document it. **Ruled: confirmed** (the S2 wording is in §9).
- **AQ-3: the sentinel is matched exactly.** `is_not_scored` matches `"NOT_SCORED"` exactly, or `scoring_outcome == "not_scored"`. Legacy readers upper-case the tier, so a hypothetical lowercase `"not_scored"` tier *with no* `scoring_outcome` would take the unaware path (require_tier_ceiling → structural). The producer only ever writes the canonical form together with `scoring_outcome`, so I left case-folding out. **Ruled: overruled; C-3 applied in §2.5** (detection case-folds the tier, validation stays exact).
- **AQ-4 (round 3, from code-reviewer S-1): ADR-level, needs a ruling.**
  - D6 lets `NOT_SCORED` stand when a validator was *skipped* (script absent, `run_validators.sh:222-225`). Yet D4 relies on "a not-scored run requires that no result errored, so losing `diff_size` cannot quietly drop the floor".
  - A skipped `diff_size` produces no outfile, so it is neither errored nor floor-hoisted. The floor vanishes silently. The same applies to a skipped weighted validator.
  - **Proposal (already in §2.4 as condition 5, with its test):** any skipped validator forces `fail_closed`, with reason `skipped: <names>`.
  - Alternative: block only on skipped weighted-or-floor-bearing dimensions. I rejected it because runner names don't map to `WEIGHTS` keys, and no registry of floor-bearing dimensions exists.
  - Cost: a partial install (a missing validator script) turns a docs PR CRITICAL, as it is today.
  - This tightens D6, so it needs the architect's ruling. If rejected, revert condition 5 and the test as noted in §2.4.
  - **Ruled (architect round 2): accepted.** ADR D6 now has five conditions and D4 cites conditions 3 and 5. The S2 binding note is in §9.
- **AQ-5 (round 4): `"SAFE"` in the C-6 rule versus its test.**
  - The C-6 rule text says "upper-cases into `TIER_ORDER`", and `require_tier_ceiling.TIER_ORDER` includes `SAFE` (`:34`). But C-6's test parametrization expects `"SAFE"` → CRITICAL.
  - I resolved it in favour of the test: §3.1 checks against `LOW..CRITICAL`. That is stricter and matches the helper's `TIERS`.
  - SAFE in this gate comes only from `compute_tier_for_pr`'s no-changed-files path (`:355-359`), never from a validator summary, so nothing legitimate changes.
  - **Ruled (architect round 3): confirmed.** `"SAFE"` → CRITICAL stands.
- **Non-question, stated so it can be checked.** The ADR (D1) says "derive from tier" for a legacy summary. I chose a concrete rule: a legacy `CRITICAL` with a top-level `error` string → `fail_closed`. This is display only; the effective tier is the same either way.

## 9. Later slices (outline, not coder-ready)
- **S1b (~6 files):**
  - All S1b readers route on `needs_helper` (round 3 `[CR-M1]`), not on `is_not_scored`.
  - `run_second_review.sh:196-225`: when the helper's `describe` says not_scored, select reviewers from `effective_tier`, not from `--score`, and never print `None` or `0` as a score. F-2 (missing key → 0) stays a separate issue.
  - `run_review_chain.sh resolve_tier` (`:155-179`): on `NOT_SCORED`, map through `validator_outcome.py effective-tier` and log `tier=<eff> (not scored: <reason>)`. Any other unknown value still `die`s.
  - `run_panel.sh` release mode (`:417-437`): record `not scored (<reason>)` instead of `unavailable`. The AD-6 MEDIUM clamp is unchanged.
  - Tests for each. `cut_release.sh` inherits from S1a.
- **S2 (~5 files, the producer):** `run_validators.sh` aggregate (`:435-521`).
  - Load the helper by path (the heredoc runs under `PYTHONSAFEPATH=1`).
  - In the legacy branch (`:468`), call `decide_zero_weight_outcome(results, schema.WEIGHTS, skipped, path_facts=path_facts)` `[CR3-3]`. The keyword is required and has no default.
  - On `fail_closed`, the summary keeps composite 1.0, `CRITICAL` and exit 1. Its top-level `error` is `decision.reason`, replacing the fixed "All validators failed…" text, so the reason names the unresolved, errored or skipped items (REQ-1717-21) `[CR3-3]`.
  - On not_scored, write the D1 summary (`composite_score: null`, `tier: NOT_SCORED`, `not_scored_reason`, `validator_outcomes`, hoisted `tier_floor`) and exit 0 (D5), so the #555 committed artifact is written.
  - Add the additive `scoring_outcome` and `validator_outcomes` to scored and fail_closed summaries.
  - Replace the shell counts line `:428` with the Python `Validators: S scored, N not applicable, E errored, K skipped`. Pass the skipped names through an env var. The verdict lines follow REQ-12.
  - An unparseable outfile (`:450-451`, today a silent `continue`) becomes errored.
  - Update the header docs for the exit codes. Reconcile #1752 per D8.
  - Header and runbook must state (AQ-2 ruling): "`validator_outcomes` is the classification of record. `composite_score` keeps the legacy truthiness exclusion (REQ-04), so a result can be counted in the composite and still be labelled errored."
  - An unparseable outfile becoming errored changes `validator_outcomes` only, never the composite. Test both halves.
  - **AQ-4 binding (architect round 2):** `skipped_names` carries **script-absent names only** (`run_validators.sh:222-225`).
    - A retry-exhausted validator has an outfile, so it is errored (D3), never skipped.
    - A validator that the file-type routing never invoked is neither skipped nor a result.
    - Passing either as skipped would make every docs PR fail closed and silently re-create #1717.
    - Required S2 test: `test_docs_deletion_only_not_scored_with_empty_skipped_list` (the routing-not-invoked validators are absent from `skipped_names`). `[SEC-M1]` renamed: a present docs file scores, so docs-only routing is not the N/A case.
  - **`[SEC-M1]` path facts (ADR D9):**
    - In `--diff` mode, collect the paths with `git -c core.quotepath=false diff -z --no-renames --name-status <ref>`, read with `read -r -d ''`. Status `D` → deleted; every other status → not deleted.
    - Use the same path list for `ALL_FILES`, replacing `:85`. This fixes git-quoted names, which today silently drop out of scoring.
    - In explicit-list mode (positional paths), `deleted` is always false, so a non-existent path is unresolved.
    - At aggregation time (cwd = repo root): `exists` = `os.path.lexists`; `protected` = `matched_surfaces([path], load_globs(<protected_surfaces.txt>))` from `scripts/framework/require_human_approval.py` (`:41`, `:79`), loaded by path. Do not re-implement the glob semantics. If the matcher fails to load, every deleted path counts as protected, which yields deleted_other → fail_closed.
    - Pass the facts to `decide_zero_weight_outcome(..., path_facts=...)`. The runner passes them to the aggregate heredoc in a NUL-separated temp file under `$TMPDIR`, cleaned on exit, never through env or argv.
    - **`[SEC-N2]` Completeness:** the helper cannot verify that `path_facts` covers every changed path, so S2 must.
      - Build `path_facts` from the exact `ALL_FILES` list that was passed to the validators, one entry per path.
      - Check explicitly that `set(path_facts) == set(ALL_FILES)`. Use an `if`, not a Python `assert`: `-O` strips asserts, and an uncaught raise under `set -e` exits before the #555 artifact is written.
      - On a mismatch, print one stderr line (`path facts incomplete: <n> missing, <m> extra`) and pass `path_facts=None`, which gives `fail_closed` "no path facts".
      - Required S2 test: `test_path_facts_cover_exactly_all_files` (equality on a normal diff, plus an injected mismatch → fail_closed).
    - Every summary (scored, not_scored, fail_closed) gains the additive key `unresolved_paths` (a sorted list, possibly empty). On scored runs it is informational only, so REQ-04 holds. Tier consequence: follow-up F-5.
    - **`[SEC-N3]`** `unresolved_paths` stays informational on scored runs (F-5). The security reviewer judged that acceptable once collection is `-z`/`core.quotepath=false` hardened.
    - **`[SEC-N1]`** `DOCS_CLASS_SUFFIXES` (`.md`/`.rst`) is a suffix test, not a docs-class proxy. See the S4 precondition below. S2 may ship the suffix rule as-is, because under the interim `CRITICAL` base a deletion-only docs diff is still CRITICAL.
    - S2 tests: deletion-only docs → not_scored; deletion-only `.py` → fail_closed (`FC_DELETED_OTHER`); a wrong checkout (listed paths absent, not deleted) → fail_closed (`FC_UNRESOLVED`); S2 tests assert `reason_code`, never position numbers `[agy3-1]`; a non-ASCII added `.py` → now scored, not N/A; a new `.md` → scored (premise correction).
  - Tests: REQ-15..18 regressions, an AC-3 counts/verdict consistency test, and a scored byte-identity fixture. Update `docs/OVERSIGHT-RUNBOOK.md`.
  - **Merge only after S1a and S1b.**
- **S3 (3 protected files, CODEOWNERS gate):** `overseer.md` step 3b plus the exec-summary clause "Composite not scored: <reason>" (REQ-14), `risk-assessor.md:102` and `oversight-evaluator.md`. Each obtains the tier through `validator_outcome.py effective-tier` / `describe`.
- **S4 (2-3 files, waits for the ESC-1 ruling):** set `NOT_SCORED_BASE_TIER` to the ruled value, update `test_not_scored_base_tier_interim_pin`, and adjust the S3 prose if needed.
  - **`[SEC-N1]` Binding precondition: this must land before `NOT_SCORED_BASE_TIER` is set below `HIGH`.**
    - The problem: instruction-bearing markdown is not all listed in `protected_surfaces.txt`. Examples: `.claude/commands/*.md`, nested `CLAUDE.md`/`AGENTS.md`, `prompts/**`, `.github/pull_request_template.md`, and the docs runbooks. Deleting any of them changes agent or human behaviour, yet today each would classify as `deleted_docs`.
    - Before a MEDIUM base ships, S2 or S4 must replace the bare suffix test in `classify_path` with one of these, so that anything else is `deleted_other`:
      - a **docs-class allowlist** (preferred: it can also exclude runbooks);
      - at minimum, an **explicit deny list**: `.claude/**`, `**/CLAUDE.md`, `**/AGENTS.md`, `prompts/**`, `.github/**`.
    - It needs its own security review and tests.
    - A base of `HIGH` or `CRITICAL` does not trigger this precondition. Under the interim `CRITICAL` base the gap is harmless.

## 10. Affected sign-offs
This is a new design and nothing has been built against it, so no prior sign-off is orphaned. It is not a startup-artifact gap: this state was never decided before ADR-1717. The re-review the ADR requires for #1752's rebase delta is unchanged.

## Architect review (round 1)

Reviewer: architect. Date: 2026-10-12. Checked against ADR-1717 D1–D8 and the code at the cited lines.

**Verdict: APPROVED WITH CONDITIONS.** S1a is coder-ready once C-1..C-4 are applied. These conditions bind the coder, and code-reviewer verifies them; a second TD round is not required. S1b, S2 and S3 are outlines and need their own TD pass before coding.

### What is correct, and why
- **§1 ordering (consumers before producer).** This is the ADR's load-bearing constraint, and the TD restates it correctly. Residual risk: nothing mechanical stops S2 merging early. The S2 PR's citation of the S1a and S1b merge SHAs is the only control, so code-reviewer must check it.
- **§2 stdlib-only, no `validators/` import.** This is correct for a trusted-base gate (`require_tier_ceiling.py:143-146` documents the `sys.path` hazard). `test_module_is_stdlib_only` makes it enforceable rather than a convention.
- **§2.4 precondition (decide only inside the legacy fail-closed branch).** This is what makes REQ-04 byte-identity structural rather than something tested for. Keep it.
- **§2.5 `effective_tier` total, never raises, every non-canonical path → CRITICAL.** This matches D7. The non-sentinel unknown → `None` in `require_tier_ceiling` (§3.1) correctly preserves the legacy blast radius.
- **§3.1 helper load failure → `"CRITICAL"`, never `None`.** Correct. `None` there means the weaker structural estimate, which is the exact fail-open the ADR exists to close.
- **§3.3 `pr_readiness` import `from scripts.oversight.validator_outcome`.** Verified: `scripts/__init__.py` exists, `scripts/oversight/` is a namespace package, and `scripts/oversight/record_agent_model.py:41` is the precedent. (The TD's `record_agent_model.py` path omits `oversight/`; the precedent itself is real.)
- **§2.2 and §5 near-miss strings → errored.** This is exactly REQ-01 and REQ-18.

### Conditions (binding)
- **C-1 (defect, `release_artifact_logic.py`). §3.2 misses the second `:.3f` site at `:524-529`** (the CLI summary print: `score={info.composite_score:.3f}`).
  - Under the interim `CRITICAL` base, a not-scored step's `effective_tier` is in `HIGH_PLUS_TIERS`, so it lands in `high_plus_steps`. That print then raises `TypeError` on `None` during `cut_release.sh`.
  - Required: print `not scored → <effective_tier>` in place of the score, and print the effective tier (not `NOT_SCORED`) in the tier column.
  - Add `test_cli_summary_prints_not_scored_step_without_typeerror`.
  - Audit the file for any other `composite_score` formatting. Every site must tolerate `None` on a not-scored info.
- **C-2 (AQ-1 count).** A re-grep finds **16 files** (the TD's own list has 16 names, so "17" is an arithmetic slip) and 19 matching lines:
  - 16 `error="no input files"` keyword arguments;
  - 2 raw_value dict literals (`ip_check.py:523`, `prompt_audit_risk.py:395`);
  - 1 comment (`prompt_audit_risk.py:325`).

  `EXPECTED_EMITTERS` is exactly those 16 files. The drift regex must ignore comments (AST string constants only, which the TD's AST approach already gives). I have corrected the ADR's Context and D2.
- **C-3 (AQ-3 — ruled differently; see below).** `is_not_scored` must detect the tier as `isinstance(tier, str) and tier.upper() == NOT_SCORED`. `validate_not_scored` stays **exact**, so a non-canonical spelling routes to the helper and then resolves to `CRITICAL`. Add `test_lowercase_sentinel_routes_to_helper_and_is_critical` in `test_require_tier_ceiling.py`.
- **C-4 (`effective_tier` consistency).** If `scoring_outcome == "fail_closed"`, return `CRITICAL` whatever `tier` says. As written, §2.5 returns `tier` unchanged for an inconsistent `{"tier": "LOW", "scoring_outcome": "fail_closed"}`. Add that case to `test_effective_tier_malformed_is_critical`.

### Rulings on §8
- **AQ-1: confirmed, with C-2.** The pin test moves to **S1a**: it pins the constant where the constant is defined, and it is test-only. The ADR's slice table is updated to match.
- **AQ-2: confirmed.** Stricter classification is correct. In the legacy branch, `total_w == 0`, so no positively-weighted result with a falsy error can be present. The stricter rule can therefore only add errored entries, and an errored entry only pushes toward `fail_closed`. That is the safe direction.
  - On scored runs, S2 must state in the script header and the runbook: "`validator_outcomes` is the classification of record. `composite_score` keeps the legacy truthiness exclusion (REQ-04), so a result can be counted in the composite and still be labelled errored."
  - The S2 counts line uses the classification. That is consistent with D3 and is not an AC-3 contradiction, because the scored verdict line does not claim "no errors".
- **AQ-3: overruled in favour of C-3.** Matching the sentinel exactly on detection leaves one fail-open: a non-canonical tier. Legacy readers upper-case it, then structural fallback gives LOW in `require_tier_ceiling`.
  - The stricter design costs nothing. Detection uses the **legacy readers' own normalisation** (`.upper()`); validation stays exact.
  - So every value a legacy reader would read as `NOT_SCORED` is caught, and anything non-canonical becomes `CRITICAL`, never LOW.
  - This does not conflict with REQ-01: the ban on fuzzy matching applies to *N/A error text*, which stays exact (`classify` row 2). It does not apply to tier routing.
- **Non-question (legacy `CRITICAL` + `error` → `fail_closed`):** accepted. It is display only, and effective-tier is identical either way.

### Notes for later slices (not S1a conditions)
- S1b `run_second_review.sh`: when not-scored, derive the score passed to `select-reviewers` from the effective tier's own threshold, or pass the tier alone. Never persist a coerced number into the sentinel file's `reason:` line as a "composite score". F-2 (missing key → `0`) stays out of scope.
- S2: an unparseable outfile becoming errored (§9) changes `validator_outcomes` only, never the composite. Test both halves.

Round count: 1 of 5. Design approved with conditions, so no `.claudetmp/design/architect-1717-*.md` state is retained.

## Architect review (round 2)

Reviewer: architect. Date: 2026-10-12. This round reviews TD round 3: CR-M1 and S-1..S-3, and the AQ-4 question.

**Verdict: APPROVED WITH CONDITIONS.** C-5 and C-6 below bind the coder and code-reviewer verifies them. No further TD round is needed. Round-1 conditions C-1..C-4 are confirmed as applied.

### needs_helper() / check_consistency() against D1/D7: consistent, with an ADR wording amendment
- **Routing on `needs_helper` is correct, and it is the right fix for CR-M1.** Routing on `is_not_scored` left `{"tier":"LOW","scoring_outcome":"fail_closed"}` on the legacy LOW path. That was a real fail-open, created by the additive `scoring_outcome` key that D1 introduced.
  - The cost is that legitimate S2 `fail_closed` summaries now enter the helper branch. That is verdict-neutral (CRITICAL either way), and §3 shows it per reader. Accepted.
  - D7's text ("helper only for the sentinel") was narrower than this. I have amended D7 to name the `needs_helper` routing set.
- **`check_consistency` matches D1.** D1 defines three outcomes with fixed tier relations: `scored` has a tier in LOW..CRITICAL, `fail_closed` is CRITICAL, and `not_scored` is the sentinel with a null composite. Every rule in §2.5 is one of those relations or a malformed-input guard.
  - `effective_tier` rule 1 (inconsistent → CRITICAL) running before rule 2 is correct. It also makes C-4 redundant-but-harmless; keep both tests.
- **Cross-check of edge cases (each must be a named test, C-6):**
  - `scoring_outcome:"scored"` + `tier:"NOT_SCORED"`: helper → `scored` with tier not in TIERS → CRITICAL. ✔
  - Sentinel under `risk_tier` only: routes to the helper → `"sentinel under non-canonical key"` → CRITICAL. In `pr_readiness`, `is_not_scored` is true → `validate_not_scored` fails (tier is not the sentinel) → REQ-W-03 fail. ✔
  - `scoring_outcome:"scored"` + `tier:"bogus"`: `needs_helper` is False → legacy path. The CR-S3 ruling below closes this in `require_tier_ceiling`. Elsewhere, the readers' existing handling of unknown tiers is already fail-closed (release integrity, review-chain `die`).
- **C-5 (spec clarity, §2.5).** `is_not_scored` is defined twice: once on `tier` only, then "with CR-S2 it also scans all LEGACY_TIER_KEYS". Rewrite it as one definition: True iff the summary is a dict and (any `LEGACY_TIER_KEYS` value is a str with `.upper() == NOT_SCORED`, or `scoring_outcome == RUN_NOT_SCORED`). The coder must not have to reconcile two texts.

### AQ-4: accepted. ADR D6 gains condition 5, and D4 is amended
- The finding is correct. D4's guarantee ("losing `diff_size` cannot quietly drop the floor") rested only on D6 condition 3, and a script-absent validator writes no outfile (`run_validators.sh:222-225`). The guarantee had a hole exactly where the TD says it did.
- "Any skipped" is the right granularity, for the reasons the TD gives: runner names do not map to `WEIGHTS` keys, there is no floor-bearing registry, and an absent script is an install defect.
- The cost (a partial install keeps docs PRs CRITICAL) equals today's behaviour, so it adds no product-boundary consequence.
- ADR D6 now has five conditions, and D4 cites conditions 3 and 5. The reason string `skipped: <names>`, and its first-match position after `errored:`, are accepted.
- **Binding on S2:** `skipped_names` carries **script-absent names only**.
  - A retry-exhausted validator has an outfile, so it is errored (D3).
  - A validator the file-type routing never invoked is neither skipped nor a result.
  - Passing either as skipped would make every docs PR fail closed again, silently re-creating #1717. S2 must test it: docs-only routing → not scored, with an empty skipped list.

### CR-S3 recorded exception: overruled. Unknown tier in a present summary → CRITICAL
- The §4 exception keeps one fail-open: a dict with no `scoring_outcome` and an unknown tier → `None` → structural estimate (possibly LOW). Its justification is D7's "don't change non-sentinel handling".
- That guard protects **legitimate** values. It was never meant to preserve fail-opens on malformed input. CR-S3 itself already tightened non-dict and unparseable files to CRITICAL on the same reasoning, so keeping this one case is internally inconsistent.
- Verified: no existing test pins unknown-tier → `None` (`tests/framework/test_require_tier_ceiling.py` only monkeypatches `_try_validator_summary`; `:252-260` asserts a valid HIGH is read). No legitimate producer path (`run_validators.sh:142`, `:185`, `:472`, `:508`, #1752) writes a dict without a valid tier. The tightening therefore changes nothing that works today.
- **C-6 (binding, §3.1 and §4).**
  - In `_try_validator_summary`: once `summary.is_file()` is true, if no `LEGACY_TIER_KEYS` value upper-cases into `TIER_ORDER`, and the summary did not route through the helper, return `"CRITICAL"`. This also covers a missing tier key.
  - An absent file still returns `None` (the CI path, unchanged).
  - Delete the §4 "Accepted D7 blast radius" bullet. Replace the planned `test_unknown_non_sentinel_tier_still_none` with `test_present_summary_unknown_tier_is_critical` (param: `"SAFE"`, `"bogus"`, missing key, `3`). Add the three cross-check cases above as named tests.
  - ADR D7 is amended to record this.

### Product-boundary check
None of the round-2 changes alters behaviour for a legitimate summary. Every change is a malformed-input or install-defect path tightening towards CRITICAL. No pm-agent or human checkpoint is needed. ESC-1 and ESC-2 are unchanged.

Round count: 2 of 5. Approved with conditions; no `.claudetmp/design/architect-1717-*.md` state is retained.

## Architect review (round 3)

Reviewer: architect. Date: 2026-10-12. This round reviews TD round 4 (C-5 and C-6 folded in) and AQ-5.

**AQ-5: confirmed. The TD's resolution stands: §3.1 validates against `LOW..CRITICAL` only, and `"SAFE"` from a summary → `CRITICAL`.**
- My C-6 phrase "upper-cases into `TIER_ORDER`" was imprecise. The test parametrization expressed the intent.
- Verified: the producer's tier table is `LOW..CRITICAL` (`run_validators.sh:487`), and nothing in the runner or `schema.py` writes `SAFE`. Inside this gate, `SAFE` is only the *computed* no-changed-files result (`require_tier_ceiling.py:355-359`).
- A summary claiming `SAFE` therefore claims a tier *below* LOW that no validator can produce. That is the "silent LOW or below" REQ-07 forbids, so `CRITICAL` is correct.
- The no-changed-files `SAFE` path does not read the summary and is unaffected. No §3.1 or §5 edit is needed.

**Final verdict on the TD as the S1a coder contract: APPROVED.**
- Conditions C-1..C-6 are all folded into the body.
- No design question is open.
- The S1b, S2 and S3 outlines need their own TD pass before coding, and S4 waits for ESC-1.
- Code-reviewer verifies against the body. These review sections are the rationale record.

Round count: 3 of 5. Approved; no `.claudetmp/design/architect-1717-*.md` state is retained.

## Architect review (round 4) — security-reviewer M1 (CWE-693)

Reviewer: architect. Date: 2026-10-12.

**Finding verified.** The three weighted validators filter their argv only by `Path(f).exists()` (`migration_scorer.py:184`, `issue_query.py:240`, `ip_check.py:516`). File type plays no part. `run_validators.sh:85` uses `git diff --name-only` without `-z`/`core.quotepath=false`, and `ALL_FILES` (`:128-129`) keeps non-existent paths. So D6 conditions 1-5 are satisfied by:
- a deletion-only diff;
- a quoted-name diff;
- a wrong checkout.

None of these are docs PRs. Under a lowered ESC-1 base, each would gain a lower tier. The premise of the issue, the requirements and the ADR ("docs-only new `.md` → N/A") is empirically false.

### Rulings
- **R4-1: option (a) adopted. ADR D6 gains conditions 6-7, and new decision D9 is added.** Not-scored now requires every changed path to be resolved (present, or a confirmed deletion) **and** to be a confirmed deletion of a non-protected `.md`/`.rst` file. Everything else in the zero-weight branch stays `fail_closed`, with an accurate reason: unresolved paths, non-docs or protected deletion, or present-but-unscored. The not-scored outcome is now exactly "a deletion-only docs diff".
- **R4-2: option (b) rejected.** Keying ESC-1 by file class would put class logic in `effective_tier` and add a summary field every reader must trust. Condition 7 gets the same safety with no new reader surface. Readers, S1b and S3 are unchanged.
- **R4-3: hardening is in S2 scope.**
  - Collect paths with `git -c core.quotepath=false diff -z --no-renames --name-status`. The same list feeds `ALL_FILES`, so quoted names stop silently dropping out of *scored* runs as well.
  - A listed path that is neither present nor a confirmed deletion is unresolved, and is treated like errored.
  - Protected-ness reuses `require_human_approval.load_globs` / `matched_surfaces`. A load failure counts as protected.
  - Every summary gains the additive key `unresolved_paths`. Its tier consequence on scored runs is follow-up F-5, so REQ-04 holds.
- **R4-4: ESC-1 is reframed and constrained.**
  - The policy now governs only resolved, deletion-only docs diffs.
  - The candidate set is MEDIUM, HIGH or CRITICAL. LOW is excluded by REQ-02/07.
  - My recommendation stays MEDIUM, because a docs deletion can still remove guidance and one agy read is cheap.
  - ESC-2 is reframed the same way. Both are still human decisions and still block only S4.

### Does the S1a contract change? Yes, in the helper only. File count unchanged (13).
- §2.1a is new: the `PATH_*` kinds, `DOCS_CLASS_SUFFIXES` and the pure `classify_path`.
- §2.4: `decide_zero_weight_outcome` gains a keyword-only `path_facts` with **no default**, conditions 6-7, a new not-scored reason format, and fail-closed reasons 2, 3, 8 and 9 with escaped, capped path rendering.
- §5: `test_decide_docs_only_new_md_is_not_scored` is replaced by `test_decide_docs_deletion_only_is_not_scored`, and eight `[SEC-M1]` tests are added.
- Readers (§3), `effective_tier`, `needs_helper` and `check_consistency` are **unchanged**.
- §9 S2 carries the path-fact collection and its tests.
- S1a is still codable before any human ruling. The §1 merge order is unchanged.

### Edits made to the TD body
§2.1a, §2.4, §5 and the §9 S2 bullets. Each is marked `[SEC-M1]`.

### Edits made to the ADR (uncommitted)
- the Context premise correction;
- D6 conditions 6-7 and their rationale;
- new D9;
- the D1 reason example;
- ESC-1 and ESC-2 reframed;
- follow-up F-5.

### REQUIREMENTS-1717 corrections required (owner: pm-agent; I have not edited the file)
1. **Problem, lines 13-17** ("For a docs-only diff that adds a new markdown file … find no file of their type, and report `error: "no input files"`"). This is wrong: they report N/A only when **none of the paths passed to them exist in the working tree**, and type does not matter. Restate the trigger as: deletion-only diffs, git-quoted paths, or a checkout lacking the PR's files.
2. **Problem, lines 27-28** ("Existing markdown files usually dodge this only because `historical_density` finds churn history — … an accident"). This is wrong: new and existing `.md` files both score whenever they exist. Delete it.
3. **Definitions, N/A, line 34** ("its input filter matched **zero** files in this diff"). Replace with "none of the paths passed to it exist in the working tree".
4. **Definitions, "Not scored", lines 44-45.** Add: "and every changed path is a confirmed deletion of a non-protected docs-class (`.md`/`.rst`) file". Also add a definition of **unresolved path**, which counts as Errored.
5. **REQ-1717-15, lines 129-130** ("docs-only diff adding a **new** `.md` file … → not-scored"). This is wrong. Replace it with two requirements: (a) a deletion-only docs diff → not scored; (b) a new `.md` file → **scored** (a regression guard for the premise).
6. **Add requirements:**
   - an unresolved changed path (wrong checkout, quoted name) → fail-closed CRITICAL, with a reason naming the paths;
   - a deletion-only diff touching non-docs or protected paths → fail-closed CRITICAL;
   - non-ASCII paths are collected unquoted.
7. **ESC-1, lines 160-169.** Option C's "a green docs PR can auto-merge" must read "a deletion-only docs PR". Remove option B or mark it excluded: it can yield LOW, which REQ-02/07 forbid. Add the constrained candidate set MEDIUM/HIGH/CRITICAL.
8. **ESC-2, lines 170-172.** Scope it to deletion-only docs diffs.

**Verdict: APPROVED WITH CONDITIONS.** The condition is that the S1a coder implements the `[SEC-M1]` body text as written. Security re-reviews S1a against R4-1 and R4-3. Requirements corrections 1-8 must land before S2's TD is finalised; they do not gate S1a.

Round count: 4 of 5. If any further design-level finding cannot be closed in round 5, it escalates to the human per the CORE round cap.
