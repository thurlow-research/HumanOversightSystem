# Technical Design — Issue #331: Extract Second-Review Threshold Comparison and Verdict Aggregation to Python

**Document type:** Technical design (contract for the coder)
**Status:** For architect review
**Issue:** #331
**Spec:** `docs/specs/SPEC-331-second-review-logic-python.md`
**Precedent:** `scripts/oversight/panel_logic.py` (SPEC-376)
**Author:** technical-design agent
**Date:** 2026-06-17

---

## 0. Architect bindings (governing)

This design is constrained by the following ratified architect bindings. Where they
resolve a spec Open Question, the binding governs.

1. **New module** `scripts/oversight/second_review_logic.py` — NOT merged into
   `panel_logic.py`. (Resolves OQ-1.)
2. **CLI shim rewrites the output file in place.** The logic function takes
   `content: str` and returns a result object; the shim reads the file, calls the
   logic, and writes the file. Logic functions NEVER touch the filesystem.
   (Resolves OQ-2 toward option (a) externally, option (b) internally: the *logic*
   is pure-string, the *shim* does the in-place rewrite.)
3. **`classify_prose` stays in this module** — not shared with `panel_logic.py`.
   Sharing is deferred. (Resolves OQ-3: defer.)
4. **Parity AC bar:** reproduce the heredoc's verdict precedence exactly:
   `error > request_changes > unparseable > approve`; an empty reviewer list →
   `error`.
5. **Stdlib only.** No subprocess, no network, no file I/O inside logic functions.
6. **Unit tests against synthetic content strings**, not integration runs.

---

## 1. Module contract — `scripts/oversight/second_review_logic.py`

### 1.1 Module-level conventions (match `panel_logic.py`)

- Module docstring stating purpose, spec/issue, purity guarantees, and which
  function does I/O (only the `__main__` shim).
- `from __future__ import annotations` immediately after the docstring.
- Stdlib imports only: `argparse`, `json`, `re`, `sys`. No third-party imports.
- Module-level constants for the severity ordering and the prose-keyword patterns,
  named with a leading underscore (e.g. `_SEVERITIES`, `_SEV_RANK`).
- All decision logic in named module-level functions; the `if __name__ ==
  "__main__"` shim is the ONLY code that reads argv / stdin / files.

### 1.2 Constants

```
_SEVERITIES = ["critical", "high", "medium", "low", "none"]
_SEV_RANK   = {s: i for i, s in enumerate(_SEVERITIES)}   # lower index = more severe
_SEV_UNKNOWN_RANK = 4   # unknown severity ranks as "none" (least severe), matching heredoc SEV_RANK.get(s, 4)
```

The verdict-precedence order is encoded as an explicit ordered check (not a rank
map) so it reads identically to the heredoc:
`error` → `request_changes` → `unparseable` → `approve`.

---

## 2. Function contracts

### 2.1 `select_reviewers(score, tier, agy_threshold, codex_threshold) -> tuple[bool, bool]`

**Signature:**
```
def select_reviewers(
    score: float,
    tier: str,
    agy_threshold: float,
    codex_threshold: float,
) -> tuple[bool, bool]
```

**Returns:** `(run_agy, run_codex)`.

> Spec R1 asks for "a named result (dataclass or dict)". The architect implementation
> bindings name this `select_reviewers(...) -> tuple[bool, bool]`. The tuple ordering
> is fixed as `(run_agy, run_codex)` and MUST be documented in the docstring so the
> CLI shim and tests cannot transpose it. This is the binding interface; the coder
> MUST NOT substitute a dict.

**Algorithm (must match shell lines 126–138 exactly):**
1. Normalize tier: `tier_uc = (tier or "").strip().upper()`.
2. `run_agy = tier_uc in {"MEDIUM", "HIGH", "CRITICAL"}` OR `score >= agy_threshold`.
3. `run_codex = tier_uc in {"HIGH", "CRITICAL"}` OR `score >= codex_threshold`.
4. Return `(run_agy, run_codex)`.

**Boundaries:**
- Comparison is `>=` (inclusive), matching `s >= t` in the heredoc.
- `score` and the thresholds are floats; the shim is responsible for `float()`
  coercion of CLI strings BEFORE calling (so the logic function never parses).
  If the logic receives non-float it is a programming error, not a runtime input —
  the function does not defensively catch.
- Tier comparison is case-insensitive and tolerant of surrounding whitespace.
- The function MUST NOT read `.env`, environment, or any threshold default. The
  defaults (`0.30`, `0.55`) live in the shell only (spec R3, §2 out-of-scope).

**Invariant:** a HIGH/CRITICAL tier forces `run_agy=True` and `run_codex=True`
regardless of score (the "tier ratchet floor", shell comment lines 114–119). A
MEDIUM tier forces `run_agy=True` only.

---

### 2.2 `classify_prose(text: str) -> str`

**Signature:** `def classify_prose(text: str) -> str`

**Returns:** a verdict string only — one of `approve`, `request_changes`,
`unparseable`.

> Design note (gap vs. heredoc): the heredoc's `classify_prose` returns a
> `(verdict, severity)` tuple. The architect binding names the extracted function
> `classify_prose(text: str) -> str` (verdict only). To preserve behavior, the
> severity half of the heredoc's prose classification is folded into the caller:
> `aggregate_verdicts` recomputes the prose severity inline using the SAME regex
> rules, OR `classify_prose` is kept tuple-returning internally and a thin
> `str`-returning public wrapper is exposed. **Binding decision for the coder:**
> implement a single private helper `_classify_prose_full(text) -> tuple[str, str]`
> holding the exact heredoc rules, and expose the public `classify_prose(text) ->
> str` as `_classify_prose_full(text)[0]`. `aggregate_verdicts` calls
> `_classify_prose_full` so it gets both verdict and severity without duplicating
> the regex. This satisfies the named-public-`str` signature AND preserves the
> severity behavior with zero rule duplication.

**Algorithm (`_classify_prose_full`, must match heredoc lines 623–637 exactly):**
```
low = text.lower()
risk      = search  r'\brisk:\s*(critical|high|medium|low|none)\b'  in low
blocking  = search  r'must[ -]?fix|tier\s*1\b|request[_ ]changes|\bblocking\b|\bcritical\b'  in low
approve   = search  r'\bverdict:\s*approve\b|no (issues|findings|problems)|lgtm|looks good|\bapprove\b'  in low

if risk and risk.group(1) in ("critical", "high"):
    return ("request_changes", risk.group(1))
if blocking:
    sev = "critical" if "critical" in low else "high"
    return ("request_changes", sev)
if approve or (risk and risk.group(1) in ("low", "none")):
    return ("approve", risk.group(1) if risk else "none")
return ("unparseable", risk.group(1) if risk else "none")
```

**Boundaries:** pure string analysis. No I/O. The regexes are byte-for-byte the
heredoc regexes — the coder MUST copy them verbatim, not paraphrase, because the
ordering of the `if` branches is load-bearing (a body containing both "critical"
and "approve" must classify as `request_changes`, because the risk/blocking checks
precede the approve check).

---

### 2.3 `aggregate_verdicts(content: str) -> dict`

**Signature:** `def aggregate_verdicts(content: str) -> dict`

**Returns:** a dict with EXACTLY these keys:
```
{
  "verdict": str,             # approve | request_changes | unparseable | error
  "highest_severity": str,    # critical | high | medium | low | none
  "unresolved_findings": int, # count of critical/high findings across all reviewers
}
```

> Spec R2 names the return fields `verdict`, `highest_severity`,
> `unresolved_findings`. These three keys are the contract. The coder MUST NOT add
> or rename keys; the shim depends on exactly these three.

**Algorithm (must match heredoc lines 599–699 exactly):**

1. **Split into sections.** `sections = re.split(r'(?m)^## ', content)[1:]` — each
   element is the text following a `## ` heading.
2. **Per-section parse** (build a list of reviewer tuples
   `(name, verdict, severity, finding_count, parsed_from)`):
   - `head` = first line of the section; `hl = head.lower()`.
   - `name = "agy" if hl.startswith("agy") else "codex" if hl.startswith("codex")
     else None`. If `None`, skip the section (it's the verdict header or an
     advisory block).
   - If `"skipped" in hl`: skip (the pre-check already handled skip).
   - `body = _fenced_body(sec[len(head):])` — see §2.4.
   - If `body` is empty after strip: append `(name, "error", "none", 0, "empty")`
     and continue.
   - Try `json.loads(body)`:
     - On `JSONDecodeError`: call `_classify_prose_full(body)` → `(v, sev)`.
       `fc = number of markdown headings in body if v == "request_changes" else 0`,
       where the heading count is `len(re.findall(r'(?m)^\s*#{1,4}\s', body))`.
       Append `(name, v, sev, fc, "prose")`. Continue.
     - On success, `data` is the parsed object:
       - If `data.get("verdict") == "error"` OR `data.get("error")` is truthy:
         append `(name, "error", "none", 0, "json")`. Continue.
       - `v = "request_changes" if data.get("verdict") == "request_changes" else
         "approve"`.
       - Walk `data.get("findings", [])`: for each finding, `s =
         str(f.get("severity","low")).lower()`; if `_SEV_RANK.get(s, 4) <
         _SEV_RANK[sev]` lower the running `sev`; if `s in ("critical","high")`
         increment `fc`.
       - Append `(name, v, sev, fc, "json")`.
3. **Aggregate:**
   - If the reviewer list is empty: `verdict="error", highest="none",
     finding_count=0`. (Binding 4: empty list → `error`.)
   - Else:
     - `highest = "none"`; for each tuple, if `_SEV_RANK.get(sev, 4) <
       _SEV_RANK[highest]` lower `highest`. Sum all `fc` into `finding_count`.
     - Collect `verds = [v for each tuple]`.
     - Verdict precedence (binding 4), in this exact order:
       `"error" in verds` → `error`;
       elif `"request_changes" in verds` → `request_changes`;
       elif `"unparseable" in verds` → `unparseable`;
       else → `approve`.
4. Return `{"verdict": verdict, "highest_severity": highest,
   "unresolved_findings": finding_count}`.

**Boundaries:**
- No file I/O — `content` is already the file text. The heredoc's `open(path).read()`
  (lines 602–605) and the final `re.sub` + `open(path,'w').write(...)` (lines
  701–704) move OUT of this function and INTO the shim (§3).
- No `print` of the human-readable progress line ("verdict=... highest=...") — that
  is the shim's responsibility (§3), kept out of the pure function.

### 2.4 `_fenced_body(text: str) -> str` (private helper)

Mirror of heredoc lines 618–621:
```
m = re.search(r'```(?:json)?\s*\n(.*)\n```', text, re.DOTALL)
return (m.group(1) if m else text).strip()
```
Returns the content inside the outer ` ```json … ``` ` block if present, else the
whole text, stripped. Pure.

---

## 3. CLI shim contract (`if __name__ == "__main__"` + `main(argv)`)

The shim is the ONLY code in the module that performs I/O. Structure mirrors
`panel_logic.main(argv)`.

### 3.1 Subcommands

Use `argparse` with two subcommands (`add_subparsers(dest="cmd")`):

**`select-reviewers`:**
- Args: `--score` (float, required), `--tier` (str, default `""`),
  `--agy-threshold` (float, required), `--codex-threshold` (float, required).
- Action: call `select_reviewers(...)`, print two lines to stdout in a
  shell-`eval`-friendly form:
  ```
  RUN_AGY=true|false
  RUN_CODEX=true|false
  ```
  Booleans rendered lowercase as `true`/`false` so the shell can `eval` or read
  them directly into its existing `RUN_AGY` / `RUN_CODEX` variables. Exit 0.

> Interface decision for the coder: emit `KEY=value` lines (not JSON) for the
> selection subcommand. The shell consumes them with a `while read` or `eval`,
> avoiding a JSON parse in bash. This keeps the shell call to a single command
> substitution. Document the exact two-line format in the shim help.

**`aggregate`:**
- Args: `--file <path>` (required) — the output file to read and rewrite in place.
- Action (binding 2 — shim does the in-place rewrite):
  1. Read the file text (`encoding="utf-8"`). On read failure: print nothing,
     exit 0 (match heredoc lines 602–605 `except: sys.exit(0)` — a missing file is
     not a hard error here; the shell's own guards handle absence).
  2. `result = aggregate_verdicts(content)`.
  3. Rewrite the three header lines in place with `re.sub` on `content`, EXACTLY
     as heredoc lines 701–703:
     - `^verdict: pending$` → `verdict: {result['verdict']}`
     - `^highest_severity: none$` → `highest_severity: {result['highest_severity']}`
     - `^unresolved_findings: 0$` → `unresolved_findings: {result['unresolved_findings']}`
     all with `flags=re.M`.
  4. Write the new content back to the file (`encoding="utf-8"`).
  5. Print the progress line to stdout:
     `  verdict={v} highest_severity={s} unresolved={n}` plus the
     `prose_note` suffix when any reviewer was parsed from prose (heredoc lines
     705–707). To compute the prose-note the shim needs to know whether any section
     parsed as prose; see §3.2.
  6. Exit 0.

### 3.2 Prose-note parity

The heredoc prints a `(parsed from prose — agy returned a markdown report, not
JSON)` suffix when `any(pf == "prose" ...)`. Because `aggregate_verdicts` returns
only the three contract keys, the shim cannot see `parsed_from`. **Binding decision
for the coder:** add a private function `_aggregate_full(content) -> tuple[dict,
bool]` that returns `(result_dict, parsed_any_prose)`. The public
`aggregate_verdicts(content) -> dict` returns `_aggregate_full(content)[0]`. The
shim calls `_aggregate_full` so it can render the prose note. This preserves the
exact stdout message AND keeps the public contract at three keys. (Same pattern as
the `classify_prose` wrapper in §2.2 — internal richer helper, public narrow
signature.)

### 3.3 Failure posture

- Per `panel_logic` precedent and spec non-requirement "no behavior change": the
  `aggregate` shim must NOT crash the pipeline. On any unexpected exception during
  aggregation, write nothing back and exit 0 (the shell's own fail-closed
  `verdict=error` guard at shell lines 767–772 still sees `verdict: pending` and
  will NOT match `error`, so the pipeline proceeds — this matches today's heredoc
  which also `sys.exit(0)`s on read failure). The verdict header stays at `pending`,
  which is a visible, non-passing sentinel.

> Note: today's heredoc has NO broad try/except around the aggregation body — only
> around the file read. To preserve behavior exactly, the shim SHOULD mirror that:
> wrap only the file read in try/except→exit 0, and let aggregation proceed. The
> coder MUST match the heredoc's actual exception surface, not add new swallowing
> that would mask a real regression. If the coder judges a broad guard is safer,
> that is a behavior change and must be raised back to this design / architect, not
> made silently.

---

## 4. Shell integration contract (`run_second_review.sh` edits)

### 4.1 Reviewer selection (replaces shell lines 125–138)

Remove the two `case "$TIER_UC"` statements and the two `python3 -c` threshold
one-liners. Replace with a single call:

```
SELECT_OUT=$(python3 "$(dirname "$0")/oversight/second_review_logic.py" \
    select-reviewers --score "$SCORE" --tier "$TIER" \
    --agy-threshold "$AGY_THRESHOLD" --codex-threshold "$CODEX_THRESHOLD")
eval "$SELECT_OUT"   # sets RUN_AGY / RUN_CODEX to true|false
```

- `TIER_UC` normalization moves into Python; the shell no longer needs it for
  selection. (If `TIER_UC` is used elsewhere in the script, keep it; a grep shows
  it is used only at lines 126/129/135, all of which are being replaced — so the
  `TIER_UC=` assignment at line 126 can be removed. The coder MUST verify with a
  grep before removing.)
- `RUN_AGY` / `RUN_CODEX` remain shell booleans (`true`/`false` command names) used
  by the rest of the script unchanged. The `eval` sets them.
- `AGY_AVAILABLE` / `CODEX_AVAILABLE` and ALL fallback / fail-closed logic (shell
  lines 140–192) stay in shell untouched — availability and launch are shell work
  (spec §2 out-of-scope).

### 4.2 Verdict aggregation (replaces shell lines 599–708)

Remove the entire `python3 - "$OUTFILE" <<'PYEOF' … PYEOF` heredoc. Replace with:

```
python3 "$(dirname "$0")/oversight/second_review_logic.py" aggregate --file "$OUTFILE"
```

The module reads `$OUTFILE`, rewrites the three header lines in place, prints the
progress line. The shell's subsequent `grep -m1 '^verdict:'` fail-closed guard
(lines 767–785) is unchanged and now reads the header the module wrote.

### 4.3 What stays in shell (unchanged)

- `salvage_review_json` (already pure-Python heredoc; out of scope per spec §2).
- `create_finding_issues` (GitHub issue creation; out of scope).
- `log_context_advisory` (SPEC-379 advisory; out of scope).
- `run_agy_review` / `run_codex_review` (CLI launch; out of scope).
- Token tracker invocation, fail-closed exit guards, header-writing of the
  `pending` sentinel.

---

## 5. Boundaries summary (what each component must NOT assume)

| Component | Must honor | Must NOT |
|---|---|---|
| `select_reviewers` | inclusive `>=`, case/whitespace-insensitive tier, tier-ratchet floor | read env/.env, parse strings, apply default thresholds |
| `classify_prose` / `_classify_prose_full` | verbatim heredoc regexes + branch order | reorder branches, paraphrase patterns, do I/O |
| `aggregate_verdicts` | exact section split, fenced-body extraction, severity ranking, verdict precedence, empty→error | read or write files, print progress, add/rename return keys |
| CLI shim | only place doing argv/stdin/file I/O; in-place rewrite of 3 header lines; exit 0 on read failure | embed decision logic; change output-file schema |
| `run_second_review.sh` | call the module; keep availability/fallback/launch/issue logic | re-implement threshold or precedence rules (spec AC6) |

---

## 6. Acceptance-criteria → contract mapping

| AC | Covered by |
|---|---|
| AC1 reviewer selection | §2.1 `select_reviewers` |
| AC2 verdict aggregation | §2.3 `aggregate_verdicts` (JSON path + severity walk) |
| AC3 prose classification | §2.2 `classify_prose` + §2.3 prose branch |
| AC4 error precedence + empty→error | §2.3 step 3 precedence + empty-list rule (binding 4) |
| AC5 shell integration | §4.1, §4.2 (skip sentinel path untouched in shell) |
| AC6 no logic duplication | §4 removes both inline `python3 -c` / heredoc blocks |

---

## 7. Test plan (unit, synthetic strings — binding 6)

New file `tests/oversight/test_second_review_logic.py`, loading the module by path
with `importlib.util` (mirror `test_panel_logic.py` lines 16–32). Tests use plain
strings/dicts; no subprocess, no file I/O, no live model.

**`select_reviewers`:**
- AC1a: `(0.45, "", 0.30, 0.55)` → `(True, False)`.
- AC1b: `(0.20, "HIGH", 0.30, 0.55)` → `(True, True)`.
- AC1c: `(0.20, "LOW", 0.30, 0.55)` → `(False, False)`.
- MEDIUM tier floor: `(0.0, "medium", 0.30, 0.55)` → `(True, False)` (lowercase).
- CRITICAL floor: `(0.0, "CRITICAL", 0.30, 0.55)` → `(True, True)`.
- Boundary equality: `(0.30, "", 0.30, 0.55)` → `(True, False)` (`>=` inclusive).
- Whitespace tier: `(0.0, " high ", 0.30, 0.55)` → `(True, True)`.

**`classify_prose`:**
- AC3a: body containing `must-fix` → `request_changes`.
- AC3b: body containing `no issues found` → `approve`.
- AC3c: unrecognizable body → `unparseable`.
- Branch-order: body with both `critical` and `approve` → `request_changes`.
- `risk: low` → `approve`; `risk: high` → `request_changes`.

**`aggregate_verdicts`:**
- AC2: agy section `verdict approve` + codex section `verdict request_changes`
  with one `high` finding → `{request_changes, high, 1}`.
- AC4: one section `verdict error` + one `request_changes` → `verdict error`.
- Empty reviewer list (content with only the header, no `## agy`/`## codex`) →
  `{error, none, 0}` (binding 4).
- Skipped section (`## agy — SKIPPED`) ignored; remaining codex approve →
  `approve`.
- Prose precedence below error: one prose-`unparseable` section + one approve →
  `unparseable`.
- Severity walk: two `critical` findings → `unresolved_findings == 2`,
  `highest_severity == critical`.
- Fenced body: a section whose JSON is inside ` ```json … ``` ` parses correctly.
- Empty body section → treated as `error` (the `"empty"` branch).

**Shim (optional, no file I/O via tmp_path only if the harness allows — otherwise
covered by AC5 integration outside this suite):** the binding scopes unit tests to
content strings, so the shim's file rewrite is validated by the `aggregate` parity
check in §4.2 during the shell run, not in the pure unit suite.

Estimated: ~7 selection + ~5 prose + ~9 aggregation = **~21 unit tests**.

---

## 8. Self-flag

RISK: low
CONFIDENCE: high
BLAST RADIUS: `run_second_review.sh` (pre-PR cross-vendor gate) + one new pure
module + one new test file. No output-file schema change, no threshold-default
change, no behavior change intended (spec §5). The refactor is mechanical
extraction with byte-for-byte regex/precedence preservation.

Change classification: **additive** (new module + tests) with a **clarifying**
in-place edit to `run_second_review.sh` that removes inline logic and calls the
module. No structural change to the pipeline contract or output schema. No human
gate triggered beyond the standard review chain.

---

## 9. Architect review requested

Two design choices resolve spec gaps created by the binding signatures and should
be confirmed:

1. **§2.2 / §3.2 narrow-public + rich-private pattern** — `classify_prose(text) ->
   str` and `aggregate_verdicts(content) -> dict` are the public binding
   signatures, but the heredoc needs prose-severity and the prose-note flag. The
   design folds those into private `_classify_prose_full` / `_aggregate_full`
   helpers so the public signatures stay exactly as bound while preserving behavior
   with zero rule duplication. Confirm this is the intended reading of bindings 2
   and 3 (no behavior change, narrow public surface).

2. **§4.1 `KEY=value` selection output + `eval`** — the selection subcommand emits
   `RUN_AGY=true`/`RUN_CODEX=true` for the shell to `eval`, rather than JSON.
   Confirm `eval` of a trusted, module-generated two-line output is acceptable here
   (inputs are numeric/tier, output is fixed-format).
