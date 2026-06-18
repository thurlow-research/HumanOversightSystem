# Requirements Spec — Issue #377: Diff-Size Risk-Tier Floor and Multi-Purpose Split Trigger

**Document type:** Requirements specification
**Status:** Draft — for architect review
**Issue:** #377
**Date:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

Watanabe et al. (2026) found that agentic PRs are empirically larger than human-authored PRs (median 48 added lines vs. 24 for humans) and far more frequently multi-purpose (39.9% vs. 12.2%). Reviewers reject oversized agent PRs precisely because review becomes impractical: the reviewer cannot hold the full change in working memory, cannot attribute findings to a single coherent intent, and cannot independently test narrowly scoped behavior.

The current HOS validator suite scores intra-file complexity (Risk Number, cyclomatic, cognitive, function metrics) and cross-file dependencies, but has no signal for the raw size or topical breadth of the diff being reviewed. A PR that consists of 600 trivially simple lines across 20 files in three distinct directories will today receive a LOW composite score even though a reviewer faces exactly the kind of review burden Watanabe et al. document.

This spec adds two deterministic floor rules to `rn_calculator.py` that constrain the tier that can be assigned regardless of the composite score:

1. **Diff-size floor** — when the diff exceeds a line-count or file-count threshold, the risk tier is promoted to HIGH at minimum.
2. **Multi-purpose split trigger** — when the diff spans enough distinct top-level domains, the validator emits an advisory warning recommending the PR be split into focused changes. This is not a hard block.

---

## 2. Scope

This spec covers:

- New logic in `scripts/oversight/validators/rn_calculator.py` that accepts diff-size metadata and applies the two rules.
- Environment-variable configuration of all three numeric thresholds (`HOS_DIFF_SIZE_FLOOR`, `HOS_FILE_COUNT_FLOOR`, `HOS_DOMAIN_SPLIT_THRESHOLD`).
- The domain-detection heuristic used to count distinct top-level domains within the changed file list.
- The output contract additions (new fields in the `make_result` envelope) so that the risk-assessor agent and `run_validators.sh` can read and act on the signals.
- A description of which rule fired, included in the validator's `raw_value` output.

This spec does not cover:

- Changes to `schema.py` score weights or tier-threshold boundaries (those are unchanged; the floor operates by overriding the derived tier, not by changing the score).
- Natural-language classification of PR purpose (the domain heuristic is purely path-prefix based; no NLP).
- The mechanism by which the risk-assessor agent promotes the tier in its final recommendation (that is existing agent behavior responding to the floor signal in the output).
- Any change to `run_validators.sh` beyond reading the new output fields (unless the architect determines the floor must be applied there; see OQ-377-A).
- Changes to any other validator.

---

## 3. Requirements

### 3.1 Diff-size input

**REQ-377-01:** `rn_calculator.py` MUST accept an optional set of diff-size inputs alongside the existing list of Python file paths. At minimum these inputs are:
- `changed_lines`: total added + deleted lines in the diff.
- `changed_files`: total count of files changed (all types, not only `.py`).

**REQ-377-02:** When `rn_calculator.py` is invoked from `run_validators.sh`, the runner MUST pass the current diff-size inputs to it. If the caller cannot determine changed-line or changed-file counts, it MUST pass `0` for each; the floor rules treat a value of `0` as "data unavailable" and do not fire.

**REQ-377-03:** `rn_calculator.py` MUST also accept the full list of changed file paths (all types) for the domain-detection heuristic. If the list is absent or empty, the split-trigger check does not fire.

### 3.2 Diff-size floor (R1)

**REQ-377-04 (R1):** If `changed_lines > HOS_DIFF_SIZE_FLOOR` OR `changed_files > HOS_FILE_COUNT_FLOOR`, the validator MUST set a `tier_floor` field in its output to `"HIGH"`.

**REQ-377-05:** The `tier_floor` field MUST be present in the output regardless of whether a floor is active. When no floor applies, the value MUST be `null` (JSON null / Python None).

**REQ-377-06:** When the floor is active, the `raw_value` dict MUST include a `floor_rule_fired` field identifying which threshold(s) were exceeded. Valid values: `"changed_lines"`, `"changed_files"`, `"both"`. When no floor applies the field MUST be `null`.

**REQ-377-07:** The diff-size floor does not affect the numeric `score` field — the score remains the Risk Number composite. The floor is a discrete promotion signal that the risk-assessor agent reads and acts on; it does not re-normalize the score.

### 3.3 Multi-purpose split trigger (R2)

**REQ-377-08 (R2):** `rn_calculator.py` MUST compute a `domain_count` by grouping changed file paths into top-level domains using the heuristic defined in §3.4 and counting distinct domains.

**REQ-377-09:** If `domain_count >= HOS_DOMAIN_SPLIT_THRESHOLD`, the validator MUST emit a split advisory in the `checklist_items` list. The advisory text MUST contain the phrase "Consider splitting into focused PRs" and MUST state the detected domain count and the threshold value.

**REQ-377-10:** The split advisory is informational only. It MUST NOT cause the validator to set `tier_floor` to any tier, and MUST NOT cause the exit code of the script to be non-zero.

**REQ-377-11:** The `raw_value` dict MUST include a `domain_count` field (integer) and a `domains_detected` field (list of strings, each being a domain label as defined in §3.4).

### 3.4 Domain-detection heuristic

**REQ-377-12:** The domain heuristic MUST operate purely on file-path prefixes. It MUST NOT perform content analysis or natural-language classification.

**REQ-377-13:** The domain mapping MUST assign each changed file path to exactly one domain label by matching the path against an ordered list of prefix rules. The default mapping is:

| Prefix match | Domain label |
|---|---|
| `.claude/agents/` | `agents` |
| `scripts/` | `scripts` |
| `docs/` | `docs` |
| `packs/` | `packs` |
| `bootstrap/` | `bootstrap` |
| `contract/` | `contract` |
| `audit/` | `audit` |
| `templates/` | `templates` |
| Any path not matching above | `other` |

**REQ-377-14:** A file that matches no prefix in the table MUST be assigned to the `other` domain. The `other` bucket counts as one domain label regardless of how many files it contains.

**REQ-377-15:** The prefix mapping defined in REQ-377-13 applies to HOS self-governance runs. Consumer projects that install HOS MUST be able to override the mapping via an environment variable (`HOS_DOMAIN_MAP`) whose format the architect will define (see OQ-377-B). If `HOS_DOMAIN_MAP` is not set, the default table in REQ-377-13 applies.

### 3.5 Configurable thresholds (R3)

**REQ-377-16 (R3):** All three numeric thresholds MUST be configurable via environment variables with the following defaults:

| Variable | Default | Semantics |
|---|---|---|
| `HOS_DIFF_SIZE_FLOOR` | `400` | Lines threshold; floor fires if `changed_lines` exceeds this value |
| `HOS_FILE_COUNT_FLOOR` | `15` | Files threshold; floor fires if `changed_files` exceeds this value |
| `HOS_DOMAIN_SPLIT_THRESHOLD` | `3` | Domain count at or above which the split advisory fires |

**REQ-377-17:** The validator MUST read these variables at startup and apply them for the entire run. If a variable is set but not parseable as a positive integer, the validator MUST log a warning to stderr and fall back to the default value.

**REQ-377-18:** A `changed_lines` or `changed_files` value of `0` MUST be treated as "data unavailable" and MUST NOT cause the floor to fire, regardless of the configured threshold. (A threshold of `0` is not a valid configuration; REQ-377-17's fallback applies.)

### 3.6 Rule-fired logging (R4)

**REQ-377-19 (R4):** When either the diff-size floor or the split trigger fires, the validator MUST write a human-readable summary to stderr indicating which rule fired, the measured value, and the configured threshold. The message MUST begin with the prefix `[diff-size]`. Example (exact wording may vary):
```
[diff-size] tier_floor=HIGH: changed_lines=512 > HOS_DIFF_SIZE_FLOOR=400
[diff-size] split advisory: domain_count=4 >= HOS_DOMAIN_SPLIT_THRESHOLD=3 (domains: agents, scripts, docs, packs)
```

**REQ-377-20:** The stderr logging MUST NOT affect stdout JSON output. The validator MUST still emit a valid `make_result`-conformant JSON object to stdout even when rules fire.

### 3.7 Output contract

**REQ-377-21:** The top-level `make_result` call for the `risk_number` dimension MUST include the following additional keys alongside the existing ones in `raw_value`:

| Key | Type | Condition |
|---|---|---|
| `tier_floor` | `str \| null` | `"HIGH"` when floor fires; `null` otherwise |
| `floor_rule_fired` | `str \| null` | `"changed_lines"`, `"changed_files"`, or `"both"` when floor fires; `null` otherwise |
| `domain_count` | `int` | Always present; `0` if no changed-file list was provided |
| `domains_detected` | `list[str]` | Always present; empty list if no changed-file list was provided |

**REQ-377-22:** The `tier_floor` value MUST also be hoisted to a top-level key on the result dict (i.e., at the same level as `score`, `dimension`, `weight`, not nested inside `raw_value`). This allows `run_validators.sh` and the risk-assessor agent to read it without parsing `raw_value`.

---

## 4. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-377-01 | When `changed_lines=512` and `HOS_DIFF_SIZE_FLOOR=400`, the result contains `tier_floor="HIGH"` and `floor_rule_fired="changed_lines"`. |
| AC-377-02 | When `changed_files=20` and `HOS_FILE_COUNT_FLOOR=15`, the result contains `tier_floor="HIGH"` and `floor_rule_fired="changed_files"`. |
| AC-377-03 | When both thresholds are exceeded, `floor_rule_fired="both"`. |
| AC-377-04 | When neither threshold is exceeded, `tier_floor=null` and `floor_rule_fired=null`. |
| AC-377-05 | When `changed_lines=0` and `changed_files=0`, the floor does not fire regardless of configured thresholds. |
| AC-377-06 | When `domain_count >= HOS_DOMAIN_SPLIT_THRESHOLD`, `checklist_items` contains a string that includes the phrase "Consider splitting into focused PRs". |
| AC-377-07 | The split advisory does not affect `tier_floor`. `tier_floor` remains `null` when only the split trigger fires. |
| AC-377-08 | Setting `HOS_DIFF_SIZE_FLOOR=10` via environment variable causes the floor to fire for `changed_lines=11`. |
| AC-377-09 | An unparseable env-var value (`HOS_DIFF_SIZE_FLOOR=abc`) logs a warning to stderr and falls back to the default (400), which does not cause the floor to fire for `changed_lines=11`. |
| AC-377-10 | The `tier_floor` key is present at the top level of the result dict (not only inside `raw_value`). |
| AC-377-11 | When a rule fires, a `[diff-size]` line is written to stderr. |
| AC-377-12 | The validator still produces valid JSON on stdout when both rules fire simultaneously. |
| AC-377-13 | For a file list of `[".claude/agents/foo.md", "scripts/bar.sh", "docs/baz.md"]`, `domain_count=3` and `domains_detected` contains `["agents", "scripts", "docs"]`. |
| AC-377-14 | A file with no matching prefix (e.g., `Makefile`) is assigned to the `other` domain and `domains_detected` includes `"other"`. |

---

## 5. Non-Requirements

- This change does not block the build. The diff-size floor raises the tier floor for the risk-assessor agent to act on; it does not cause `run_validators.sh` to exit non-zero by itself.
- This change does not introduce NLP or semantic classification of commit messages, PR titles, or file content.
- This change does not modify `schema.py` score weights, tier-threshold boundaries, or any other validator.
- The split trigger is advisory only. It cannot by itself cause a CONDITIONAL or ESCALATE outcome from the risk-assessor.
- This change does not alter how the risk-assessor agent derives its final tier recommendation; the agent already reads `tier_floor` signals and acts on them if that field is non-null.

---

## 6. Open Questions for Architect

**OQ-377-A:** The diff-size inputs (`changed_lines`, `changed_files`, changed-file path list) currently flow to `rn_calculator.py` which is a per-file Python complexity scorer. Should the diff-size floor logic live in `rn_calculator.py` as this spec describes, or should it be a separate validator (e.g., `diff_size_validator.py`) with its own entry in `run_validators.sh` and `schema.py` WEIGHTS? The separate-validator approach is cleaner separation of concerns; the in-place approach avoids adding a new dimension weight. Architect should decide.

**OQ-377-B:** REQ-377-15 requires that consumer projects can override the domain-prefix map. What is the correct env-var format? Options include: a JSON blob, a colon-separated list of `prefix:label` pairs, or a path to a TOML/YAML file. Architect should specify the format and whether the override replaces or extends the default map.

**OQ-377-C:** REQ-377-22 requires `tier_floor` as a top-level key on the result dict. `schema.py`'s `make_result()` does not currently support arbitrary top-level fields beyond its defined signature. Should `make_result` be extended with an optional `tier_floor` parameter, or should the caller add the key after calling `make_result`? Architect should decide and confirm whether a `schema.py` change is needed.

**OQ-377-D:** How should `run_validators.sh` pass the changed-file list and line counts to `rn_calculator.py`? Candidates are: new CLI flags (`--changed-lines N --changed-files N --changed-file-list f1 f2 ...`), a JSON sidecar file, or reading from a git diff directly inside the validator. Architect should specify the interface so that `run_validators.sh` and the validator are consistent.
