# Requirements Spec — Issue #373: Task-Class Deterministic Risk-Tier Floor

**Document type:** Requirements specification
**Status:** REVISED — ready for architect re-review
**Issue:** #373
**Date:** 2026-06-17
**Revised:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

Two independent SLR findings — Ferdous et al. (2026) and Watanabe et al. (2026) — demonstrate
that agentic PRs break backward compatibility at substantially different rates depending on
task class. Maintenance-oriented task classes carry disproportionate breakage risk:

| Task class | Breaking-change rate |
|------------|---------------------|
| `chore`    | 9.35%               |
| `refactor` | 6.72%               |
| `fix`      | 2.69%               |
| `feat`     | 2.89%               |

The current composite-score pipeline (`rn_calculator.py` + weighted validators) is calibrated
on code structure and static signals. It has no mechanism to account for task-class breakage
risk: a trivially simple refactor or chore commit scores structurally LOW and is reviewed at
LOW intensity, even though the empirical breakage probability is more than 2x that of a new
feature of equivalent structural complexity.

This spec adds a deterministic floor rule that prevents structurally LOW code from bypassing
MEDIUM-intensity review when the task class is known to be high-risk.

---

## 2. Scope

This spec covers exactly two artifacts:

1. **`scripts/oversight/validators/rn_calculator.py`** — extended to accept task-class context
   and apply the floor rule before emitting its result. The floor is placed in
   `rn_calculator.py` because the issue specifically directs it there and that script is
   already the canonical location of the RN threshold logic that produces the initial tier
   signal read by downstream consumers.

2. **`scripts/oversight/run_validators.sh`** — extended to accept and pass through a
   `--task-class <class>` argument so the caller (the risk-assessor agent or a human running
   the script directly) can supply task-class context to `rn_calculator.py`. The shell
   script performs the git/gh detection (R1a/R1b) as a pre-step and passes the result
   to `rn_calculator.py` via `--task-class`. The detection logic is NOT duplicated inside
   the Python validator.

No other validators, no schema weights, and no tier-threshold constants in `schema.py` are
in scope.

### Out of scope

- Changes to the RN formula itself (nesting increments, judgment increments, `_NESTING_TABLE`).
- Semantic classification of free-form commit messages beyond the prefix-token match described
  in R1.
- Any change to how `schema.py` defines tier thresholds or composite scoring.
- Propagation of the floor to validators other than `rn_calculator.py`.
- Any new UI, dashboard, or report output beyond the existing JSON envelope.
- Retroactive re-scoring of previously merged PRs.

---

## 3. Requirements

### R1 — Detect task class

The system must detect the task class of the current change set from one of two sources,
tried in priority order:

**R1a (primary): Conventional-commit prefix in the git commit subject.**
The system reads the subject line of `HEAD` (or the commit being validated). If the subject
matches the pattern `^(feat|fix|refactor|chore)(\(.+\))?[!]?:`, the task class is the
matched token (`feat`, `fix`, `refactor`, or `chore`). Matching is case-insensitive.
Tokens not in that set are treated as unknown.

**R1b (fallback): GitHub issue label.**
If R1a does not yield a known task class, the system checks whether the issue referenced by
`HEAD`'s commit message (first `#NNN` reference) carries a GitHub label whose name exactly
matches one of `feat`, `fix`, `refactor`, or `chore`. If exactly one matching label is
found, that label value is the task class. If zero or more than one matching label is found,
the task class remains unknown.

R1b is only attempted when a GitHub issue reference is present in the commit message and
`gh` is available on the path. R1b failure (network unavailable, `gh` not available, API
error) must not cause the validator to fail — treat as unknown and continue.

### R2 — Apply the floor

`rn_calculator.py` computes an **RN-local tier** from its own normalized `score` (0.0–1.0)
using the same thresholds defined in `schema.py` `TIER_THRESHOLDS`: score < 0.30 → LOW,
0.30 ≤ score < 0.55 → MEDIUM, 0.55 ≤ score < 0.78 → HIGH, score ≥ 0.78 → CRITICAL.

The floor is applied to that **RN-local tier only**. `rn_calculator.py` does NOT modify
`summary.json`'s tier — the composite tier remains the risk-assessor agent's
responsibility, computed downstream from the weighted composite of all validator scores.

When the task class is `refactor` or `chore` and the RN-local tier is `LOW`, the floor
is applied: the RN-local tier is raised to `MEDIUM`. The floor does not lower a tier
that is already `MEDIUM`, `HIGH`, or `CRITICAL`.

When the task class is `feat` or `fix`, no floor is applied; the RN-local tier is emitted
unchanged.

### R3 — Log the source and floor outcome

The validator output JSON must record, in the `raw_value` object, five additional fields:

- `task_class`: the detected task class string (`"feat"`, `"fix"`, `"refactor"`, `"chore"`)
  or `null` if unknown.
- `task_class_source`: one of `"commit_prefix"`, `"github_label"`, or `null` (if task class
  is unknown or was not applied).
- `floor_applied`: boolean — `true` if R2 raised the RN-local tier, `false` otherwise.
- `pre_floor_tier`: the RN-local tier before floor logic ran (`"LOW"`, `"MEDIUM"`, `"HIGH"`,
  or `"CRITICAL"`), or `null` if task class was unknown (floor was never evaluated).
- `post_floor_tier`: the RN-local tier after floor logic ran — equals `pre_floor_tier` when
  no floor was applied, `"MEDIUM"` when the floor raised a `"LOW"` tier, or `null` if task
  class was unknown.

All five fields must be present in the output regardless of whether the floor was applied.

The floor logic must be expressed in a thin wrapper function `apply_task_class_floor()`
called from `main()`, not from inside `analyse_files()`. This keeps the RN calculation
itself unmodified and testable in isolation.

### R4 — Fail open if unknown

When the task class is unknown or absent (R1a and R1b both yield no result), no floor is
applied. The validator emits the tier computed from the RN score without modification.
`task_class` is `null`, `task_class_source` is `null`, and `floor_applied` is `false`.

Unknown task class must never cause the validator to exit with a non-zero status code or
to emit an `error` field in its JSON output solely because the task class was absent.

---

## 4. Acceptance Criteria

### AC1 — Task-class detection (covers R1)

AC1a: Given a commit with subject `refactor: simplify auth flow`, the system detects task
class `refactor` from source `commit_prefix`.

AC1b: Given a commit with subject `chore(deps): update lodash`, the system detects task
class `chore` from source `commit_prefix`.

AC1c: Given a commit with subject `feat!: add SSO`, the system detects task class `feat`
from source `commit_prefix`.

AC1d: Given a commit with subject `build: update CI config` (non-standard prefix), the
system detects no task class; `task_class` is `null`.

AC1e: Given a commit with no matching prefix but a `#NNN` reference, and the referenced
issue carries exactly one label `refactor`, the system detects task class `refactor` from
source `github_label`.

AC1f: Given a commit with no prefix and no issue reference, the system detects no task
class; `task_class` is `null`.

AC1g: Given `--task-class refactor` passed directly to `rn_calculator.py`, the system uses
that value without invoking git or `gh`. (Direct caller override is supported.)

### AC2 — Floor application (covers R2)

AC2a: Given task class `refactor` and an RN score that maps to RN-local tier `LOW`
(score < 0.30), `raw_value.pre_floor_tier` is `"LOW"`, `raw_value.post_floor_tier` is
`"MEDIUM"`, and `floor_applied` is `true`. The composite tier in `summary.json` is NOT
modified by this validator.

AC2b: Given task class `chore` and an RN-local tier of `LOW`, `raw_value.post_floor_tier`
is `"MEDIUM"` and `floor_applied` is `true`.

AC2c: Given task class `refactor` and an RN-local tier of `MEDIUM` (score ≥ 0.30),
`raw_value.pre_floor_tier` and `raw_value.post_floor_tier` are both `"MEDIUM"` and
`floor_applied` is `false`.

AC2d: Given task class `refactor` and an RN-local tier of `HIGH` (score ≥ 0.55),
`raw_value.pre_floor_tier` and `raw_value.post_floor_tier` are both `"HIGH"` and
`floor_applied` is `false`.

AC2e: Given task class `feat` and an RN-local tier of `LOW`, `raw_value.post_floor_tier`
is `"LOW"` and `floor_applied` is `false`.

AC2f: Given task class `fix` and an RN-local tier of `LOW`, `raw_value.post_floor_tier`
is `"LOW"` and `floor_applied` is `false`.

### AC3 — Log fields (covers R3)

AC3a: The `raw_value` object in the validator JSON output always contains the keys
`task_class`, `task_class_source`, `floor_applied`, `pre_floor_tier`, and `post_floor_tier`,
regardless of whether a floor was applied.

AC3b: When the floor is applied, `floor_applied` is `true`, `task_class_source` is one of
`"commit_prefix"` or `"github_label"`, `pre_floor_tier` is `"LOW"`, and `post_floor_tier`
is `"MEDIUM"`.

AC3c: When the floor is not applied because task class is unknown, `task_class` is `null`,
`task_class_source` is `null`, `floor_applied` is `false`, `pre_floor_tier` is `null`, and
`post_floor_tier` is `null`.

AC3d: When task class is known but no floor was applied (tier was already MEDIUM or above,
or task class is `feat`/`fix`), `pre_floor_tier` and `post_floor_tier` are both the
un-floored RN-local tier string (e.g. `"MEDIUM"`, `"HIGH"`), and `floor_applied` is `false`.

### AC4 — Fail open (covers R4)

AC4a: When neither git nor `gh` yields a task class (or neither is available), the
validator exits with status 0 and emits valid JSON with `error` either `null` or absent.

AC4b: When the `gh` API call in R1b fails with a network error, the validator continues,
treats the task class as unknown, and does not set the `error` field in the output JSON.

AC4c: Running `rn_calculator.py` without passing any task-class argument produces identical
output to current behavior for all non-floor code paths (no regression).

---

## 5. Non-Requirements

The following are explicitly out of scope and must not be built as part of this issue:

- **No change to the RN formula.** Nesting increments, judgment increments, and the
  `_NESTING_TABLE` calibration are unchanged.
- **No semantic NLP classification.** Task class is detected only from exact prefix-token
  matching and exact label matching. The system does not attempt to infer task class from
  commit message prose.
- **No new schema weights.** `schema.py` `WEIGHTS` and `TIER_THRESHOLDS` are unchanged.
- **No floor propagation to other validators.** Only `rn_calculator.py` applies the floor.
  The composite score and tier in `summary.json` continue to be computed from the raw
  validator scores via `composite_score()`. It is the responsibility of the risk-assessor
  agent (which reads the JSON output) to interpret the `floor_applied` signal if needed
  for its final tier ruling.
- **No new required validator arguments.** `--task-class` is optional in both
  `rn_calculator.py` and `run_validators.sh`; existing call sites require no change.
- **No environment variable propagation.** `--task-class` is a CLI argument only.
  `rn_calculator.py` does not read `TASK_CLASS` or any other environment variable to
  infer task class. Future validators that need task-class context must receive it
  through their own CLI arguments, not through a shared environment variable.
- **No git or gh invocations inside rn_calculator.py.** The R1a/R1b detection logic
  (reading git commit subjects, calling `gh` for issue labels) is performed exclusively
  as a shell pre-step in `run_validators.sh`, not inside the Python validator. The
  Python validator receives task class only via `--task-class`.

---

## 6. Architect Rulings (resolved)

The following implementation decisions were submitted as open questions and ruled upon by
the architect (REQUEST_CHANGES response, 2026-06-17). All three rulings have been
incorporated into the spec above.

**OQ-1 (floor logic placement):** Floor logic must live in a thin wrapper function
`apply_task_class_floor()` called from `main()`, not inside `analyse_files()`. The RN
calculation itself remains unmodified and testable in isolation. — Incorporated in R3.

**OQ-2 (CLI arg vs. env var):** `--task-class` is a CLI argument only; no environment
variable propagation. `rn_calculator.py` does not read `TASK_CLASS` from the environment.
— Incorporated in §2 and §5 non-requirements.

**OQ-3 (git/gh detection location):** The R1a/R1b detection (git commit subject + `gh`
issue label lookup) is performed as a shell pre-step in `run_validators.sh`, not inside
`rn_calculator.py`. The Python validator receives only the resolved `--task-class` value.
— Incorporated in §2 and §5 non-requirements.
