# SPEC-334: Move dedup-ledger fingerprinting and verdict aggregation to Python

**Status:** Draft — for architect review
**Issue:** #334
**Policy:** #314 — prefer Python for logic, shell for launch; testability is a code review criterion
**Date:** 2026-06-17

---

## 1. Problem statement

Both `scripts/framework/validate_agents.sh` and `scripts/framework/validate_scripts.sh` implement two identical correctness-critical logic blocks entirely in inline Python heredocs embedded inside bash:

1. **Deduplication ledger fingerprinting** — reads `external-review-ledger.jsonl` (or `scripts-review-ledger.jsonl`), builds a set of `(sorted files, finding-class)` fingerprints, and marks findings as "seen" vs. "new." The verdict is keyed on NEW (un-ledgered) blocking findings; this fingerprinting is the mechanism by which the external review converges to zero new findings rather than looping indefinitely.

2. **Verdict aggregation across reviewers** — parses multiple JSON reviewer blocks from the output file, extracts findings/attacks, resolves severity to a canonical ordering, counts blocking findings, separates new from seen, and writes the final `verdict:`, `highest_severity:`, `blocking_count:`, and `new_blocking_count:` header fields back into the output file.

Both scripts contain these two blocks as `python3 - ... <<'PYEOF' ... PYEOF` heredocs. The logic is essentially identical between the two scripts but is duplicated rather than shared. Heredoc Python cannot be unit-tested, linted, or imported — it is logic in a string.

Per policy #314, this logic should live in an importable Python module.

---

## 2. Current behavior (identical logic in both scripts)

### 2a. Dedup ledger — fingerprint schema

The ledger files (`external-review-ledger.jsonl`, `scripts-review-ledger.jsonl`) are append-only JSONL files. Each line is:

```json
{"files": ["file1.md", "file2.md"], "class": "<category|type>", "disposition": "<fixed|filed:#N|residual|noise>", "ts": "<ISO-8601>"}
```

A fingerprint is `(tuple(sorted(files)), class_string)`. A finding is considered "seen" if its fingerprint matches any ledger entry regardless of disposition. The dedup is reliable within a vendor (the same finding re-phrased next run gets the same fingerprint) and best-effort across vendors (agy uses `category`; codex uses `type` for the same concept).

The `--record FILES CLASS DISPOSITION` CLI subcommand (implemented in bash in both scripts) writes a new ledger entry. The `--reset` subcommand removes the ledger and pass-count file.

### 2b. JSON extraction — `_brace_objects` and `extract_objects`

`validate_agents.sh` implements a more sophisticated JSON extractor (`_brace_objects`) that handles:
- String-aware brace matching (does not get fooled by `{` inside a JSON string value)
- Escape sequence tracking (`\\` before `"`)
- Extraction from inside ` ```json ``` ` fences first, falling back to bare brace scanning

`validate_scripts.sh` implements a simpler extractor:
```python
for blk in re.findall(r'```json\s*(.*?)```', content, re.DOTALL):
    try: data=json.loads(blk[blk.index('{'):])
```
This does not handle the brace-in-string case.

The two implementations are not identical. The Python module must implement the more robust `_brace_objects` approach from `validate_agents.sh`.

### 2c. Severity ranking

Both scripts use a severity ordering to find the highest severity across all findings. `validate_agents.sh`:
```python
severities = ["critical", "high", "blocking", "warning", "medium", "low", "none"]
```
`validate_scripts.sh`:
```python
sev = ["critical","blocking","high","warning","none"]
# and maps critical/high → "blocking" before ranking
```
These are inconsistent. The architect should specify the canonical ordering (see OQ-1).

### 2d. Verdict logic

Both scripts use the same rule: `verdict = "request_changes" if new_blocking > 0 else "approve"`. An `"error"` verdict is returned only if no reviewer JSON blocks were parsed (`validate_agents.sh` only; `validate_scripts.sh` does not have this case explicitly — it exits 0 with zero findings if no blocks parse).

### 2e. Header rewrite

Both scripts use `re.sub` to rewrite four header fields in the output file in-place:
- `verdict: pending` → `verdict: <computed>`
- `highest_severity: none` → `highest_severity: <computed>`
- `blocking_count: 0` → `blocking_count: <N>`
- `new_blocking_count: 0` → `new_blocking_count: <N>`

### 2f. Pass-cap enforcement

`validate_scripts.sh` enforces the pass cap inside the heredoc Python (exits 3 if `passn >= maxp` and `new > 0`). `validate_agents.sh` enforces it in bash after the heredoc runs (checks `$PASS_NUM >= $EXTERNAL_REVIEW_MAX_PASSES`). The Python module must expose the computed values so the shell can enforce the cap, or the module can return an exit code. Architect decision (see OQ-2).

---

## 3. Scope

### What moves to Python (`scripts/oversight/validation_logic.py`, new module)

| Logic | Current location | Target |
|---|---|---|
| Ledger read + fingerprint set construction | Both scripts (heredoc lines ~452–461 in agents; ~187–190 in scripts) | `load_ledger(ledger_path: str) -> set[tuple]` |
| Finding fingerprint computation | Both scripts | `fingerprint(finding: dict) -> tuple` |
| JSON extraction from output file (robust brace matcher) | `validate_agents.sh` heredoc | `extract_reviewer_blocks(content: str) -> list[dict]` |
| Severity ranking + highest computation | Both scripts | `highest_severity(findings: list[dict]) -> str` |
| Blocking count + new-vs-seen split | Both scripts | `aggregate_verdict(blocks: list[dict], seen: set) -> dict` returning `{verdict, highest_severity, blocking_count, new_blocking_count}` |
| Header field rewrite | Both scripts | `rewrite_header(content: str, verdict_data: dict) -> str` |
| Ledger entry write (the `--record` operation) | Both scripts (bash) | `record_ledger_entry(ledger_path, files, cls, disposition)` |

### What stays in shell

- Argument parsing (`--record`, `--reset`, `--changed-only`, `--base`, `--skip-agy`, `--skip-codex`, etc.)
- CLI availability checks (`agy`, `codex`, `claude`)
- Running the reviewer processes (`run_capped`, `run_agy`, `run_codex`, `run_reviewer`)
- Writing the output file header (initial `verdict: pending` block)
- Pass-count file management
- Reading the output file and calling `python3 scripts/oversight/validation_logic.py` to compute and rewrite the verdict

---

## 4. Requirements

**R1 — Extract ledger fingerprinting.** `validation_logic.py` must expose `load_ledger(path)` which reads a JSONL ledger file and returns the set of `(sorted-files-tuple, class-string)` fingerprints. It must tolerate a missing ledger file (return an empty set) and malformed lines (skip them).

**R2 — Extract `aggregate_verdict`.** `validation_logic.py` must expose a function that accepts a list of parsed reviewer JSON blocks (each with a `findings` or `attacks` list) and the seen-fingerprint set, and returns a dict with `verdict`, `highest_severity`, `blocking_count`, and `new_blocking_count`. This is the function unit tests can call directly with fixture data.

**R3 — Extract `rewrite_header`.** `validation_logic.py` must expose a function that accepts the output file content string and the verdict dict and returns the updated content string with the four header fields rewritten. This must not write to disk — the shell or the CLI entry point writes the file.

**R4 — Extract `record_ledger_entry`.** `validation_logic.py` must expose a function (or CLI entry point) that appends one JSONL entry to a ledger file. This replaces the bash `--record` heredoc in both scripts.

**R5 — Both shell scripts delegate to the module.** `validate_agents.sh` and `validate_scripts.sh` must replace their `python3 - "$OUTFILE" "$LEDGER" <<'PYEOF' ... PYEOF` heredocs with a call to `python3 scripts/oversight/validation_logic.py <args>`. No Python logic remains inline in either bash script.

**R6 — Unit-testable without a live model run.** All functions in `validation_logic.py` must be exercisable from a Python unit test by passing fixture strings and tmp paths. No subprocess invocation inside the module. No dependency on the output of an agy/codex run.

**R7 — Robust JSON extraction.** The module must implement the string-aware brace matcher from `validate_agents.sh` (`_brace_objects`), not the simpler `validate_scripts.sh` variant. The more robust implementation must serve both scripts.

**R8 — Behavior parity with both scripts.** The computed verdict, counts, and header rewrite must be identical to what each script currently computes for the same input. Any discrepancy is a regression.

**R9 — Stdlib only.** No third-party dependencies. Consistent with all other `scripts/oversight/*.py` modules.

---

## 5. Non-requirements

- This change does not alter the ledger format, fingerprint schema, or disposition values.
- This change does not change the verdict logic (`request_changes` if new_blocking > 0, else `approve`).
- This change does not change the output file format or the header fields.
- This change does not modify how reviewers are invoked (agy, codex, claude remain shell-invoked).
- This change does not unify the two separate ledger files into one (the agents ledger and the scripts ledger remain separate, each script manages its own).
- No new features. No new validation checks.

---

## 6. Open questions for architect

**OQ-1 (canonical severity ordering):** `validate_agents.sh` and `validate_scripts.sh` use inconsistent severity orderings (see §2c above). The Python module must use one canonical ordering. The architect should decide: (a) use the `validate_agents.sh` ordering (`critical > high > blocking > warning > medium > low > none`) treating `blocking` as an alias for severity between `high` and `warning`, or (b) use the `validate_scripts.sh` approach of collapsing `critical`/`high` into `blocking` before ranking. This is the only behavioral discrepancy between the two scripts and must be resolved before implementation.

**OQ-2 (pass-cap exit code):** `validate_scripts.sh` currently exits with code 3 from inside the heredoc Python when the pass cap is hit and new findings remain. `validate_agents.sh` checks the pass cap in bash after the heredoc. The module should return enough information (the `new_blocking_count`) for the shell to enforce the cap itself, rather than encoding exit-code semantics in the module. The architect should confirm this is the preferred interface, or specify an alternative.

**OQ-3 (module placement):** The issue specifies `scripts/oversight/validation_logic.py`. The existing `scripts/oversight/*.py` validators use a similar convention. The architect should confirm this path or redirect (e.g., `scripts/framework/validation_logic.py` since these scripts live in `scripts/framework/`).

**OQ-4 (`--record` unification):** The `--record` subcommand is currently implemented identically in both bash scripts. If `validation_logic.py` exposes a `--record` CLI entry point, both scripts can delegate to it and the bash duplication is eliminated. The architect should confirm this is in scope for this issue or whether ledger-entry writing should stay in bash.
