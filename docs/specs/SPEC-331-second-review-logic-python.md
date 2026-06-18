# Requirements Spec — Issue #331: Move Second-Review Threshold Comparison and Verdict Aggregation to Python

**Document type:** Requirements specification
**Status:** Draft — for architect review
**Issue:** #331
**Milestone:** v0.5.0 — Quality
**Date:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

`scripts/run_second_review.sh` currently contains two categories of logic that violate the
#314 policy ("prefer Python for logic, shell for launch — establish testability as a code
review criterion"):

1. **Threshold comparison** (lines 126–138): the decision of whether to fire `agy` and/or
   `codex` is made by inline `python3 -c` one-liners embedded in bash. These are not
   individually named, not importable, and not unit-testable without running the full shell
   script.

2. **Verdict aggregation** (lines 599–707): a 100-line inline `python3 - "$OUTFILE" <<'PYEOF'`
   heredoc that reads the second-review output file, parses all reviewer JSON blocks,
   classifies prose responses, computes the aggregate severity and verdict, and rewrites the
   output file in place. This is the most logic-dense section of the script and is entirely
   untestable in isolation.

Both categories involve deterministic rules: float comparison against configured thresholds,
severity ordering, and verdict precedence. They are exactly the logic class that #314 targets
for extraction. A bug in either category can silently pass a step that should have been
blocked (e.g., the existing HOS#113 fix history shows how fragile inline verdict parsing has
been).

The shell script's remaining work — resolving CLI availability, launching `agy` and `codex`,
writing the output file header, logging advisories, creating GitHub issues, recording token
usage — is genuinely shell work and stays in shell.

---

## 2. Scope

### In scope

- Extract the **reviewer-selection logic** (should agy fire? should codex fire? what is the
  combined availability+threshold decision?) into named Python functions in a new module at
  `scripts/oversight/second_review_logic.py`.
- Extract the **verdict aggregation logic** (parse reviewer sections, classify prose,
  aggregate severities, compute final verdict, rewrite the output file header) into named
  Python functions in that same module.
- The shell script must be updated to call the Python module for these decisions; it must
  not re-implement the logic.
- The module must be unit-testable with synthetic input without running `run_second_review.sh`
  or any live model.

### Out of scope

- The prompt construction for agy/codex reviewers — stays in shell.
- The `run_agy_review` and `run_codex_review` shell functions — they launch CLIs, stays
  in shell.
- The `salvage_review_json` logic — this is already a pure Python heredoc and may be
  migrated in a future issue; this spec does not require it.
- The `create_finding_issues` GitHub issue creation logic — stays in shell.
- The `log_context_advisory` SPEC-379 advisory logic — stays in shell.
- The token tracker invocation — stays in shell.
- The fail-closed exit at the end of the script (`verdict=error` guard) — the shell exit
  is correct and stays; the Python module informs the verdict value the shell checks.
- Threshold values themselves (`OVERSIGHT_AGY_THRESHOLD`, `OVERSIGHT_CODEX_THRESHOLD`) —
  these remain environment-configurable via `.env`; the Python module receives them as
  arguments, not as hardcoded constants.

---

## 3. Requirements

### R1 — Reviewer-selection function

The module must expose a function that determines which reviewers should fire for a given
step, given:
- `score: float` — the composite risk score for the step
- `tier: str` — the validated risk tier (e.g., `"HIGH"`, `"MEDIUM"`, `""`)
- `gy_threshold: float` — the configured agy firing threshold
- `codex_threshold: float` — the configured codex firing threshold

The function must return a named result (dataclass or dict) indicating:
- Whether agy should run (`run_agy: bool`)
- Whether codex should run (`run_codex: bool`)

The determination must match the current shell behavior exactly:
- agy fires if `tier` is MEDIUM, HIGH, or CRITICAL (case-insensitive), OR if
  `score >= agy_threshold`.
- codex fires if `tier` is HIGH or CRITICAL (case-insensitive), OR if
  `score >= codex_threshold`.

### R2 — Verdict aggregation function

The module must expose a function that reads the text content of a second-review output
file and computes the aggregate verdict. The function must accept:
- `content: str` — the full text of the output file (not a file path)

The function must return a named result (dataclass or dict) containing:
- `verdict: str` — one of `approve`, `request_changes`, `unparseable`, `error`
- `highest_severity: str` — the highest severity seen across all reviewer findings
  (one of `critical`, `high`, `medium`, `low`, `none`)
- `unresolved_findings: int` — count of critical/high findings across all reviewers

The aggregation logic must match the current inline heredoc behavior exactly:

- The output file is split into reviewer sections on `## ` headings.
- Each section is identified as `agy` or `codex` by its heading prefix; sections
  with `skipped` in the heading are ignored.
- Each section body is parsed: the content inside a ` ```json ... ``` ` fenced block
  is tried as JSON first; if absent the whole body is tried.
- A section that parses as valid JSON with `verdict: error` or an `error` key is
  classified as `error`.
- A section that parses as valid JSON with a `findings` array has its findings
  examined for severity; `critical` and `high` findings increment the unresolved
  count.
- A section whose body cannot be parsed as JSON is classified by the prose-analysis
  heuristic (`classify_prose`), which returns a verdict and severity based on
  keyword matching (see current heredoc lines 624–637 for the exact rules).
- Verdict precedence (most severe wins): `error` > `request_changes` >
  `unparseable` > `approve`. An empty reviewer list produces `verdict=error`.

### R3 — Shell calls Python for both decisions

The shell script must invoke the Python module for:

1. The reviewer-selection decision: replacing the current inline `python3 -c` comparisons
   (lines 130–138) with a single call to the R1 function.
2. The verdict aggregation: replacing the current inline heredoc (lines 599–707) with a
   call to the R2 function.

The shell script must not duplicate the decision logic. Threshold values and tier strings
are passed to the Python module as arguments; the module does not read `.env` directly.

### R4 — Unit-testable without a live model run

The functions introduced by R1 and R2 must perform no subprocess calls, no file I/O (other
than accepting content as a string argument), and no network calls. They must be importable
and callable in a Python unit test with synthetic inputs.

A CLI shim (`if __name__ == "__main__"`) may perform file I/O for the shell integration,
but the underlying logic functions must be pure.

---

## 4. Acceptance Criteria

**AC1 — Reviewer selection is correct:** Given `score=0.45, tier="", agy_threshold=0.30,
codex_threshold=0.55`, the R1 function returns `run_agy=True, run_codex=False`. Given
`score=0.20, tier="HIGH", agy_threshold=0.30, codex_threshold=0.55`, the function returns
`run_agy=True, run_codex=True`. Given `score=0.20, tier="LOW", agy_threshold=0.30,
codex_threshold=0.55`, the function returns `run_agy=False, run_codex=False`.

**AC2 — Verdict aggregation is correct:** Given a synthetic output file string containing
one agy section with `"verdict": "approve"` and one codex section with `"verdict":
"request_changes"` and a `high`-severity finding, the R2 function returns
`verdict="request_changes", highest_severity="high", unresolved_findings=1`.

**AC3 — Prose classification is correct:** Given a synthetic output file where the agy
section body contains the phrase `"must-fix"` but is not valid JSON, the R2 function
returns `verdict="request_changes"`. Given a section body containing `"no issues found"`,
the function returns `verdict="approve"`. Given a section body that is neither JSON nor
recognizable prose, the function returns `verdict="unparseable"`.

**AC4 — Error precedence:** Given an output file where one section has `verdict=error` and
another has `verdict=request_changes`, the R2 function returns `verdict="error"`.

**AC5 — Shell integration:** Running `run_second_review.sh --step 1 --score 0.10 --tier LOW`
exits 0 with a `verdict: skipped` sentinel file, with no change to current skip behavior.
Running with `--score 0.67 --tier HIGH` (with mock reviewers that return synthetic JSON)
produces an output file whose `verdict:` line matches what the current script produces.

**AC6 — No logic duplication:** The shell script contains no inline `python3 -c` fragments
that implement threshold comparison or verdict precedence rules after this change.

---

## 5. Non-Requirements

- **No behavior change.** The refactored script must produce identical output files and
  identical exit codes to the current script for all inputs within the existing contract.
- **No new review features.** This spec does not add new reviewer types, new verdict values,
  or new severity levels.
- **Shell still launches the model.** The `run_agy_review` and `run_codex_review` shell
  functions are unchanged; the Python module never invokes a model CLI.
- **No change to the output file format.** The `step{N}-{TS}.md` files written to
  `.claudetmp/second-review/` have the same schema before and after this change.
- **No change to threshold configuration.** Thresholds remain environment-variable-
  configurable via `OVERSIGHT_AGY_THRESHOLD` and `OVERSIGHT_CODEX_THRESHOLD` in `.env`.

---

## 6. Open Questions

**OQ-1 — Module placement**
This spec names the new module `scripts/oversight/second_review_logic.py` by analogy with
the existing `panel_logic.py`. The architect should confirm this path or redirect to a
different location (e.g., a shared `scripts/oversight/review_logic.py` that serves both
`run_second_review.sh` and `run_panel.sh` uses).

**OQ-2 — Shell integration interface**
The shell script currently calls the aggregation heredoc by passing the output file path as
a positional argument (`python3 - "$OUTFILE" <<'PYEOF'`). The Python module could be called
as: (a) a CLI that reads the file path and rewrites it in place (same interface as current),
or (b) a CLI that reads content on stdin and writes the updated content to stdout (the shell
handles file read/write). Option (b) keeps the module purer but requires two shell lines
instead of one. The architect should rule on the preferred interface.

**OQ-3 — Shared `classify_prose` logic**
The `classify_prose` heuristic (keyword-based verdict/severity extraction from non-JSON
reviewer responses) exists in both `run_second_review.sh` (lines 624–637) and implicitly
in the panel flow. If the architect decides both scripts should share this logic, the function
could live in a shared utility module. This spec does not require sharing; it extracts for
`second_review_logic.py` only. The architect should rule on whether sharing is warranted now
or deferred.

---

## 7. Context for Architect

- The reviewer-selection logic in `run_second_review.sh` is currently split across
  lines 126–138: two `case` statements set boolean flags, then two `python3 -c` one-liners
  raise those flags based on score comparison. The R1 function consolidates this into one
  named, testable function.
- The verdict aggregation heredoc is at lines 599–707. It rewrites the output file in place
  (lines 701–703) after computing the new verdict/severity/count values. The R2 function
  returns those computed values; the shell or a CLI shim handles the file rewrite.
- The existing `panel_logic.py` (SPEC-376) sets the precedent for this extraction pattern:
  pure Python functions, a CLI shim for the shell integration, no I/O in the logic layer.
  The architect may choose to have `second_review_logic.py` follow the same structural
  conventions.
- Issue #314 is the policy driver. Issue #333 extracts panel-specific logic to the already-
  seeded `panel_logic.py`; issue #332 adds more panel logic to that same module. This issue
  (#331) targets the second-review script, which is a distinct pipeline stage.
