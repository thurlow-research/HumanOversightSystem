# Technical Design — SPEC-334: validation_logic.py

**Issue:** #334
**Spec:** `docs/specs/SPEC-334-validation-logic-python.md`
**Architect ruling:** GO (8 bindings, recorded below)
**Author:** technical-design
**Date:** 2026-06-17
**Status:** READY FOR CODER

---

## 0. Self-flag (HOS authoring)

**RISK:** MEDIUM — correctness-critical convergence logic (the gate that stops the
external-review loop) moves from two inline heredocs into one shared module. The
classification is **additive-with-one-deliberate-correction**: the module is new,
the shell delegates to it, and `validate_scripts.sh`'s `highest_severity` output
changes from collapsed-`blocking` to canonical `critical`/`high` (spec §2c, AC-1).
That output change is a contract change for an already-shipped script.

**CONFIDENCE:** HIGH — the source logic exists and is read line-by-line below; the
precedent module `second_review_logic.py` (SPEC-331) is a near-identical refactor
with the same purity/CLI-shim shape.

**BLAST RADIUS:** `scripts/oversight/validation_logic.py` (new), the verdict +
`--record` paths of `validate_agents.sh` and `validate_scripts.sh`. The dedup
ledger schema, the verdict rule, and the agents-script `highest_severity` output
are unchanged.

### Human Review Required

This is a MEDIUM design change touching the external-review convergence gate.
A reviewer must confirm: (a) the 7-rank canonical ordering is applied to BOTH
scripts (binding 2), (b) the shell still owns the pass-cap and exit codes
(binding 3), and (c) the `validate_scripts.sh` `highest_severity` change is
accepted as the intended correction (spec §2c / AC-1), not a regression.

**Affected sign-offs:** none re-opened. No code has been approved against a prior
`validation_logic.py` contract (the module is new). The `validate_scripts.sh`
heredoc was never separately signed off as a contract; its `highest_severity`
collapse is the bug being fixed. → **no startup-artifact-gap**; this is the first
contract for this logic.

---

## 1. Architect bindings (authoritative)

| # | Binding |
|---|---|
| 1 | New module `scripts/oversight/validation_logic.py`. |
| 2 | Canonical severity ordering: 7-rank from `validate_agents.sh` — `critical > high > blocking > warning > medium > low > none`. Do NOT collapse critical/high to blocking. |
| 3 | Shell owns the pass-cap. Module returns `new_blocking_count`; shell enforces count + exit code. Module CLI emits process exit codes ONLY for operational failure, never for verdict logic. |
| 4 | `--record` unified: both scripts delegate `--record` to Python. Module writes the ledger entry. `--reset` stays in shell. |
| 5 | Fingerprint checks BOTH `category` AND `type` (agy=`category`, codex=`type`); prefer whichever present. AC-2: a `type`-only finding matches a ledger entry recorded with the same class string. |
| 6 | Robust `_brace_objects` extractor from `validate_agents.sh` (string-aware, escape-tracking, fence-first-then-bare-scan) is the single extractor for both scripts. |
| 7 | No-blocks-parsed: `--strict-empty` flag. Set → empty parse yields `"error"` verdict (agents behavior). Unset → exit 0 (scripts compat). Default OFF. |
| 8 | stdlib only; never sources `config.sh`; no subprocess/network/file-I/O in logic functions. |

---

## 2. Module contract — `scripts/oversight/validation_logic.py`

stdlib only (`argparse`, `json`, `re`, `sys`). **Purity invariant (binding 8):**
the four logic functions below take/return plain values and perform NO subprocess,
network, or file I/O — except `record_ledger_entry`, whose sole job is one ledger
append (the file write is its defined operation, not an incidental side effect).
The CLI shim (`main`) is the only place that reads argv and reads/writes the
output file in place.

### 2.1 `extract_json_objects(text: str) -> list[dict]`

The robust `_brace_objects` + `extract_objects` pipeline from `validate_agents.sh`
(lines 402–446), copied behavior-for-behavior.

- **Inner brace walk** (`_brace_objects`-equivalent, may stay a private helper):
  scan `text` for each `{`; from there track `depth`, `in_str`, `esc`; on a
  string-aware return to `depth == 0`, attempt `json.loads(text[i:j+1])`; append
  on success, silently skip on exception; resume scanning at `j+1`.
- **Outer fence-first scan**: for each ` ```json … ``` ` fence
  (`re.finditer(r"```json(.*?)```", text, re.DOTALL)`), collect brace-objects that
  contain `findings` OR `attacks` OR `verdict`. If the fence pass yields nothing,
  fall back to a bare scan of the whole `text`, keeping objects with `findings`
  OR `attacks`.
- **Returns** the list of parsed dict blocks (reviewer JSON blocks).

**Boundary:** must not raise on malformed JSON, braces inside strings, or escaped
quotes. Must not assume a fence is present (codex/agy prepend prose).

### 2.2 `fingerprint(finding: dict) -> str`

> Spec/issue task names this `-> str`. The legacy heredocs use a tuple
> `(tuple(sorted(files)), class)`. Both are equivalent dedup keys; the module
> standardizes on a **stable string** so the public signature matches the task
> and the value is trivially comparable/serializable. The internal ledger
> comparison (§2.3) uses the SAME function on both sides, so the representation
> choice is self-consistent and AC-2 holds regardless of tuple-vs-string.

- **files**: `finding.get("files")` if present and truthy; else
  `[finding["file"]]` if a singular `file` key is present; else `[]`. Sort them.
- **class**: `finding.get("category") or finding.get("type") or ""` — prefer
  `category` (agy), fall back to `type` (codex), then empty (binding 5).
- **Returns** a deterministic string key, e.g. the JSON of
  `[sorted_files, class]` via `json.dumps(..., sort_keys=True)`, or an equivalent
  delimiter-joined form. The exact spelling is the coder's choice **provided**
  the ledger side (§2.3) is fingerprinted by the identical rule.

**AC-2:** a finding with `type` only and a ledger entry recorded with the same
class string MUST produce equal fingerprints (same files, same class). A finding
with `category` only and the same class string also matches.

### 2.3 `compute_verdict(findings, ledger_path, *, strict_empty=False) -> dict`

> Issue task signature: `compute_verdict(findings: list[dict], ledger_path: str)`.
> `findings` here is the list of **parsed reviewer blocks** (each a dict with a
> `findings` and/or `attacks` list) as returned by `extract_json_objects`. The
> ledger is read by this function from `ledger_path` (the one read-only file
> access permitted in the verdict path; reading a ledger is this function's
> defined input, mirroring the heredoc which opened the ledger inline). `strict_empty`
> carries binding 7.

Algorithm (from `validate_agents.sh` 449–493, canonicalized):

1. **Load ledger → seen set.** Read `ledger_path` line by line; for each non-empty
   line, `json.loads`; build the seen key from `(sorted(entry["files"]), entry["class"])`
   using the SAME rule as `fingerprint`. Tolerate `FileNotFoundError` (empty set)
   and malformed lines (skip). (Spec R1.)
2. **Severity order:** `["critical", "high", "blocking", "warning", "medium", "low", "none"]`
   (binding 2 — applied to BOTH scripts; no collapse).
3. **Iterate blocks:** for each parsed block, for each item in
   `block.get("findings", []) + block.get("attacks", [])`:
   - `sev = str(item.get("severity", "low")).lower()`
   - if `severities.index(sev) < severities.index(highest)` → update `highest`
     (guard `ValueError` for unknown severities; leave `highest` unchanged).
   - if `sev in ("critical", "high", "blocking")`: `blocking_count += 1`; if
     `fingerprint(item)` not in seen → `new_blocking_count += 1`.
4. **Verdict:**
   - if no blocks parsed AND `strict_empty` → `verdict = "error"`.
   - elif no blocks parsed AND not `strict_empty` → `verdict = "approve"`,
     all counts 0 (scripts-compat: the shell then exits 0; binding 7).
   - elif `new_blocking_count > 0` → `"request_changes"`.
   - else → `"approve"`.
5. **Returns** `{"verdict", "highest_severity", "new_blocking_count", "dedup_count"}`
   where `dedup_count = blocking_count - new_blocking_count` (the count of
   blocking findings suppressed by the ledger). `blocking_count` itself is also
   included so the shell can rewrite that header field.

> **Return dict keys (authoritative):** `verdict`, `highest_severity`,
> `blocking_count`, `new_blocking_count`, `dedup_count`. The issue task lists
> `{verdict, highest_severity, new_blocking_count, dedup_count}`; `blocking_count`
> is added because both scripts rewrite a `blocking_count:` header line and need
> the value. `dedup_count` = `blocking_count − new_blocking_count`.

**Boundary:** `compute_verdict` does NOT decide pass/fail exit codes and does NOT
read the pass counter (binding 3 — shell owns the cap). It does NOT write the
output file.

### 2.4 `record_ledger_entry(finding, ledger_path) -> None`

> Issue task signature: `record_ledger_entry(finding: dict, ledger_path: str)`.
> The CLI `record` subcommand (§3) assembles `finding` from `--files/--class/--disposition`
> argv and calls this. This is the unified `--record` writer (binding 4).

- Build `{"files": [...], "class": cls, "disposition": disp, "ts": <ISO-8601 UTC>}`.
  - `files`: from `finding["files"]` (already a list).
  - `class`: `finding["class"]`.
  - `disposition`: `finding["disposition"]`.
  - `ts`: `datetime.now(timezone.utc)` formatted `%Y-%m-%dT%H:%M:%SZ` — matches the
    bash `date -u +"%Y-%m-%dT%H:%M:%SZ"` both scripts produce today.
- Append exactly ONE `json.dumps(...)` line + `\n` to `ledger_path` (create if
  absent; `mkdir -p` the parent is the shell's responsibility, but the function
  opens in append mode). No read, no dedup on write — append-only, matching the
  current bash behavior.

**Boundary:** writes exactly one line; never rewrites or truncates the ledger.

---

## 3. CLI shim — `__main__`

`argparse` with two subcommands. **Exit codes (binding 3):** `0` on success for
both subcommands regardless of verdict; non-zero ONLY on operational failure
(bad args, unwritable ledger). The shell reads the rewritten header (or the
printed values) and decides pass/fail.

### 3.1 `process` — main verdict path

```
validation_logic.py process --file OUTFILE --ledger LEDGER [--strict-empty]
```

1. Read `OUTFILE`. If unreadable → return 0 (the shell's own guards handle a
   missing file; matches `validate_agents.sh` 396–399 `sys.exit(0)`).
2. `blocks = extract_json_objects(content)`.
3. `result = compute_verdict(blocks, args.ledger, strict_empty=args.strict_empty)`.
4. Rewrite the four header lines in place with `re.sub(..., flags=re.M)`, exactly
   as the heredocs do:
   - `^verdict: pending$` → `verdict: {verdict}`
   - `^highest_severity: none$` → `highest_severity: {highest_severity}`
   - `^blocking_count: 0$` → `blocking_count: {blocking_count}`
   - `^new_blocking_count: 0$` → `new_blocking_count: {new_blocking_count}`
5. Write `OUTFILE` back.
6. Print the summary line:
   `  verdict={v} highest_severity={h} blocking={b} new={n}` (preserves existing
   stdout that the shells already grep/echo).
7. Return 0.

> Note: the in-place rewrite + file write live in the shim, NOT in
> `compute_verdict` (binding 8 purity). `compute_verdict` is the unit-test seam.

### 3.2 `record` — unified ledger write (binding 4)

```
validation_logic.py record --ledger LEDGER --files "a.md,b.md" --class CLS --disposition DISP
```

- Split `--files` on `,` into a list (matches the bash `awk -F,` CSV→JSON-array).
- Call `record_ledger_entry({"files": [...], "class": CLS, "disposition": DISP}, LEDGER)`.
- Print `Recorded to ledger: [a.md,b.md] CLS → DISP` (the calling script may add
  its own ledger-name prefix in its echo).
- Return 0.

---

## 4. Shell modifications

### 4.1 `validate_agents.sh`

- **Verdict (lines 392–501, the `python3 - "$OUTFILE" "$LEDGER" <<'PYEOF' … PYEOF`):**
  replace the entire heredoc with:
  ```sh
  python3 scripts/oversight/validation_logic.py process \
      --file "$OUTFILE" --ledger "$LEDGER" --strict-empty
  ```
  `--strict-empty` is set here (binding 7 — agents script returns `error` on empty
  parse). The downstream bash (508–538) that greps `verdict:`/`blocking_count:`/
  `new_blocking_count:` and enforces `$PASS_NUM >= $EXTERNAL_REVIEW_MAX_PASSES`
  is UNCHANGED (binding 3 — pass-cap stays in shell).
- **`--record` (lines 80–89):** replace the inline `awk` + `printf >> "$LEDGER"`
  body with a delegation:
  ```sh
  python3 scripts/oversight/validation_logic.py record \
      --ledger "$LEDGER" --files "$_files" --class "$_cls" --disposition "$_disp"
  echo "Recorded to external-review ledger: [$_files] $_cls → $_disp"
  ```
  (Keep the `mkdir -p "$OUT_DIR"` and the script-specific echo.)
- **`--reset` (91–95):** UNCHANGED (binding 4 — reset stays in shell).

### 4.2 `validate_scripts.sh`

- **Verdict (lines 178–211, the heredoc):** replace with:
  ```sh
  python3 scripts/oversight/validation_logic.py process \
      --file "$OUTFILE" --ledger "$LEDGER"
  rc=0
  ```
  **No `--strict-empty`** (binding 7 — scripts compat: empty parse → approve/exit-0).
  The pass-cap exit-code logic that lived inside the heredoc
  (`sys.exit(0 if new==0 else (3 if passn>=maxp else 1))`, line 209) MOVES INTO
  THE SHELL (binding 3): after the `process` call, the shell reads
  `new_blocking_count` (and `verdict`) from the rewritten header and sets `rc`:
  ```sh
  NEW=$(grep '^new_blocking_count:' "$OUTFILE" | head -1 | awk '{print $2}')
  if   [[ "${NEW:-0}" -eq 0 ]];                  then rc=0
  elif [[ "$PASS_NUM" -ge "$MAX_PASSES" ]];      then rc=3
  else                                                rc=1
  fi
  ```
  The existing `if [[ $rc -eq 0 ]] … elif $rc -eq 3 … else …` echo block (215–223)
  and `exit $rc` are preserved — this reproduces the old exit-code contract
  (0 converged / 3 escalate-cap / 1 fail) now that the module no longer emits it.
- **`--record` (lines 50–58):** delegate to `validation_logic.py record` exactly
  as in §4.1 (keep the scripts-ledger echo).
- **`--reset` (59–61):** UNCHANGED.

> **Behavior parity (spec R8):** the agents path is byte-identical in computed
> values. The scripts path is identical in verdict/`blocking_count`/`new_blocking_count`/
> exit codes; ONLY `highest_severity` changes (now canonical 7-rank — a `critical`
> finding reports `critical`, not collapsed `blocking`). This is AC-1, the intended
> §2c correction.

---

## 5. Acceptance criteria → verification

| AC | Verification |
|---|---|
| **AC-1** | Unit test: `compute_verdict` over a block with a `severity: critical` finding returns `highest_severity == "critical"`; and the `validate_scripts.sh process` path rewrites `highest_severity: critical` (not `blocking`). |
| **AC-2** | Unit test: `fingerprint({"files":["a.sh"],"type":"bash"})` equals the ledger key built from a recorded entry `{"files":["a.sh"],"class":"bash"}`; symmetric test with `category` only. `compute_verdict` then counts that finding as seen (not new). |
| R6/R8 | Unit tests call `extract_json_objects`, `fingerprint`, `compute_verdict`, `record_ledger_entry` directly with fixture strings + `tmp_path` ledgers — no subprocess, no live model. |

Test file: `tests/oversight/test_validation_logic.py` (mirror the `importlib`
loader pattern from `test_second_review_logic.py`). Required coverage:
empty-parse strict vs non-strict (binding 7); brace-in-string extraction
(binding 6); fence-absent bare-scan; category/type fingerprint symmetry (AC-2);
critical not collapsed (AC-1); ledger dedup (new vs seen split); `record`
round-trip (write then read back into the seen set).

---

## 6. Out of scope (spec §5)

Ledger format, fingerprint schema, disposition values, the verdict rule, the
output-file format, reviewer invocation, and ledger-file unification are all
unchanged. No new validation checks.

---

## 7. Architect review request

Design drafted per the 8 bindings. Requesting architect review before coder
hand-off. Open confirmation points (all resolved by bindings, restated for the
record):
- §2.2 standardizes `fingerprint -> str` (issue signature) while §2.3 fingerprints
  the ledger side identically — confirm the representation choice is left to the
  coder so long as both sides use one rule.
- §2.3 adds `blocking_count` to the return dict (beyond the issue's 4-key list)
  because both shells rewrite a `blocking_count:` header. Confirm additive key OK.
- §4.2 moves the scripts-path exit-code computation from heredoc Python into shell
  (binding 3). Confirm the `0/3/1` mapping is reproduced faithfully.
