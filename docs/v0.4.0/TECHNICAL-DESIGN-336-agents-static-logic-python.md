# Technical Design — Issue #336: `agents_static_logic.py`

**Document type:** Technical design
**Status:** For architect review
**Issue:** #336
**Spec:** `docs/specs/SPEC-336-agents-static-logic-python.md`
**Module:** `scripts/oversight/agents_static_logic.py`
**Consumer:** `scripts/framework/check_agents_static.sh` (sections 3 and 4)
**Author:** technical-design
**Date:** 2026-06-17

---

## 0. Architect bindings honored

This design implements the architect's bindings verbatim:

1. New module at `scripts/oversight/agents_static_logic.py` (OQ-1 resolved → `scripts/oversight/`).
2. **FOUR** public functions — OQ-2 resolved: the `grep -oE` raw-extraction at line 128 is
   promoted to a Python function `extract_path_refs`, in addition to the three the spec named.
3. Shell integration: **stdin** for the two text functions (`extract_path_refs`,
   `extract_escalation_targets`); **argv** for the two per-item functions (`filter_path_ref`,
   `classify_token`). Stdin for text eliminates the `open('$f')` shell-quoting hazard (spec §1.1).
4. `PROJECT_NON_AGENT_TOKENS` and `EXTERNAL_AGENTS` are passed **as arguments**; the module
   never sources `config.sh`.
5. Section 5 (doc-path consistency) stays in shell — OUT OF SCOPE (OQ-3 resolved → defer).
6. Stdlib only; no subprocess, network, or file I/O inside the logic functions.

---

## 1. Module contract

### 1.1 Public surface

```python
extract_path_refs(agent_text: str) -> list[str]
filter_path_ref(ref: str, output_docs: set[str]) -> str          # "SKIP" | "CHECK"
extract_escalation_targets(agent_text: str) -> list[str]
classify_token(
    token: str,
    known_agents: set[str],
    non_agent_tokens: str,        # pipe-joined ERE alternation, e.g. "human|you|main"
    known_labels: str,            # pipe-joined ERE alternation
    known_short_agents: str,      # pipe-joined ERE alternation
    external_agents: str,         # pipe-joined ERE alternation (may be "")
) -> str                          # "SKIP" | "EXTERNAL" | "CHECK"
```

**Return-value design note (binding / spec §R2, §R3):** the classification functions return
**bare strings** (`"SKIP"` / `"CHECK"` / `"EXTERNAL"`), not an enum. Rationale: the consumer is a
shell `case`/`if` branch that compares stdout text; a bare string is the simplest faithful
contract across the process boundary and matches the precedent of returning printable tokens. The
constants are still named module-level (`SKIP`, `CHECK`, `EXTERNAL`) so the pure functions and
their unit tests reference symbols, not string literals.

**Parameter-type design note:** `classify_token` accepts the four classification lists as
**pipe-joined strings** (the exact ERE alternation strings the shell already assembles —
`NON_AGENT_TOKENS`, `KNOWN_LABELS`, `KNOWN_SHORT_AGENTS`, `EXTERNAL_AGENTS`), not as `set[str]`.
Rationale: the shell already owns these as pipe-joined strings (lines 144–145, 158, 160, and
`EXTERNAL_AGENTS` from `config.sh`); passing them through unchanged keeps the shell ↔ Python
boundary a single argv string per list and removes any tokenization ambiguity. Membership is
tested by **exact match against the split tokens**, which reproduces the shell's anchored
`grep -qE "^($LIST)$"` semantics exactly (see §2.4). `known_agents` is the one true set (it is
matched with `grep -qx` line equality in shell; the function does set-membership). The spec §R2
type signature (`set[str]`) is satisfied behaviorally — the shell-facing CLI builds the comparison
from the argv string; an importing unit test may pass either form because the helper normalizes.

### 1.2 Constants

```python
SKIP = "SKIP"
CHECK = "CHECK"
EXTERNAL = "EXTERNAL"
```

---

## 2. Per-function specification (contract, not code)

### 2.1 `extract_path_refs(agent_text) -> list[str]` (R3 extraction half / OQ-2)

**Replaces:** line 128 `grep -oE` pipeline (extraction only — NOT the filter cascade).

**Must compute:** apply the exact pattern the shell `grep -oE` uses, ported to Python `re`:
```
`[A-Za-z][A-Za-z0-9_./-]+/[A-Za-z0-9_./-]+\.(md|yaml|html|css|sh|py|json)[^`]*`
```
The shell pipeline then does `tr -d '`'` and `grep -v '^http'`. The function must reproduce all
three stages:
1. `re.findall` of the backtick-delimited pattern across the **full** text (the shell grep is
   line-oriented but the pattern contains no newline class, so per-line and whole-text findall
   yield identical matches — the pattern cannot span a `\n`; confirmed because `[^`]*` excludes
   nothing but the pattern body is anchored by a literal `` ` `` on both ends and ERE `.`-free).
2. Strip the surrounding backticks from each match (equivalent to `tr -d '`'`). Because the
   capture must return the inner path text, the implementation captures the inside of the
   backticks in a group rather than post-stripping, which is equivalent and avoids stripping any
   stray backtick inside an anchor fragment (there are none — `[^`]*` forbids interior backticks).
3. Drop any match beginning with `http` (equivalent to `grep -v '^http'`).

**Returns:** list of raw reference strings in document order, backticks removed, http-prefixed
dropped. **Must not** apply the SKIP/CHECK cascade — that is `filter_path_ref`'s job. Empty text
or no matches → `[]`.

**Boundary it must honor:** the regex alternation group `(md|yaml|...)` is a *grouping*; `findall`
with a group returns the group, not the whole match. The implementation must therefore use a
**non-capturing** group `(?:md|yaml|...)` for the extension and wrap the whole path in the single
capturing group, so `findall` returns the full path string.

### 2.2 `filter_path_ref(ref, output_docs) -> "SKIP"|"CHECK"` (R3 filter half)

**Replaces:** lines 112–122 per-reference guard cascade.

**Must compute** — cleaning then the six-guard cascade, in this exact order (matching lines
112–119):

Cleaning (line 112 `tr -d '`"' | sed 's/#.*//' | xargs`):
1. Remove all backtick and double-quote characters.
2. Truncate at the first `#` (drop anchor fragment).
3. `xargs`-equivalent whitespace strip: collapse to a single shell-word — operationally this
   trims leading/trailing whitespace. (No agent path ref contains interior spaces; if one did,
   `xargs` would keep only the first word. The function reproduces `xargs` faithfully by taking
   `.split()[0]` when the cleaned string is non-empty, else `""`. This matches `xargs` on the
   empty string → empty output.)

Cascade — return `SKIP` if ANY is true, else `CHECK`:
1. cleaned starts with `http` → SKIP (line 113)
2. cleaned is empty → SKIP (line 114)
3. cleaned has no `/` → SKIP (line 115, bare filename)
4. cleaned starts with `{` → SKIP (line 116, template placeholder `{SPEC_FILE}`)
5. cleaned starts with `PROJECT/` → SKIP (line 117, consumer-project path)
6. cleaned ∈ `output_docs` → SKIP (lines 119–121, output-doc exemption)

**Ordering fidelity:** the shell checks `http*` (113) before empty (114). An empty string is not
`http*`, and `http*` is non-empty, so the two are independent — order is immaterial between them,
but the function preserves shell order regardless. The output-doc check is last because it
compares the fully-cleaned string.

**Returns** `CHECK` only when the reference survives all six guards. The existence test (`[[ -e ]]`)
stays in shell — the function never touches disk (R5).

### 2.3 `extract_escalation_targets(agent_text) -> list[str]` (R1)

**Replaces:** the inline `python3 -c` at lines 178–184.

**Must compute:** `re.findall` of the **exact** current pattern (spec §R1, lines 181):
```
(?i:escalat\w+\s+to|invok\w+|receives?\s+from|notif\w+)[^`]*`([a-z][a-z0-9_-]+)`
```
Single capturing group → the agent-name candidate. `re.findall` returns the group across the full
text in document order (AC2 order requirement). No-match → `[]` (R1, AC4 — no behavior change:
this is the same regex, so the same false positives/negatives as today).

**Boundary:** the pattern is byte-for-byte the inline one. The `(?i:...)` inline-flag group makes
only the verb alternation case-insensitive — preserved exactly. The function does no token
classification — that is `classify_token`.

### 2.4 `classify_token(token, known_agents, non_agent_tokens, known_labels, known_short_agents, external_agents) -> "SKIP"|"EXTERNAL"|"CHECK"` (R2)

**Replaces:** lines 151–172 of the shell inner loop (the per-token decision; `[[ -z ]]` empty-skip
at line 151 and the final `grep -qx "$KNOWN_AGENTS"` existence test at 173 stay in shell — see
§3.2 boundary).

**Must compute** the three-stage exclusion cascade in this exact order (the architect's
"three-stage exclusion cascade"), matching shell lines 153–172:

1. **Non-agent token** (line 153, `grep -qE "^($NON_AGENT_TOKENS)$"`): if `token` exactly equals
   one of the pipe-split `non_agent_tokens` entries → `SKIP`.
2. **Known label** (line 161): if `token` exactly equals one of the pipe-split `known_labels`
   entries → `SKIP`.
3. **Hyphen heuristic** (lines 164–166): if `token` is NOT in `known_short_agents` AND contains
   no `-` → `SKIP`.
4. **External** (lines 169–171): if `external_agents` is non-empty AND `token` exactly equals one
   of its pipe-split entries → `EXTERNAL`.
5. Otherwise → `CHECK`.

**Empty-list fidelity:** the shell guards `non_agent_tokens` always non-empty (seeded with
`human|...`); `external_agents` may be empty, in which case the shell `[[ -n "$EXTERNAL_AGENTS" ]]`
short-circuits — the function reproduces this by treating an empty `external_agents` string as "no
external agents" (no token can match, so never `EXTERNAL`). Splitting `""` on `|` must yield an
empty membership set, never a set containing `""` (else a literal empty token would match) — the
helper drops empty fragments.

**Anchored-match fidelity (critical):** the shell uses `^($LIST)$` — full-string anchored. The
Python membership test must be **exact equality against split tokens**, NOT substring and NOT
regex search, to reproduce the anchoring. E.g. `non_agent_tokens="human|you"` must match `"human"`
exactly, never `"human2"` or `"superhuman"`.

**Returns** exactly one of `SKIP` / `EXTERNAL` / `CHECK`. The three-way distinction is required
because the shell emits a distinct external message (spec §7) and a distinct resolve/fail for
`CHECK`.

---

## 3. CLI shim (`__main__`)

### 3.1 Subcommand dispatch

```
agents_static_logic.py extract-path-refs            # stdin: agent text; stdout: one ref/line
agents_static_logic.py filter-path-ref <ref> [<output_doc>...]    # argv; stdout: SKIP|CHECK
agents_static_logic.py extract-escalation-targets   # stdin: agent text; stdout: one name/line
agents_static_logic.py classify-token <token> <known_agents> \
        <non_agent_tokens> <known_labels> <known_short_agents> <external_agents>
                                                     # argv; stdout: SKIP|EXTERNAL|CHECK
```

- `extract-*`: read all of stdin, call the function, print each list item on its own line
  (preserving order). Empty list → no output. Matches the current shell `while read` consumption.
- `filter-path-ref`: `ref` is argv[2]; remaining argv are the `output_docs` members (passed by the
  shell as separate args). Print the single result token.
- `classify-token`: six positional args. `known_agents` is passed as a newline- or pipe-joined
  string — design choice: **pipe-joined** for consistency with the other four list args; the CLI
  splits it into the membership set. `known_short_agents`, `known_labels`, `non_agent_tokens`,
  `external_agents` are the shell's existing pipe-joined ERE strings, passed verbatim.

**I/O boundary (binding 6 / R5):** ONLY the `__main__` shim touches stdin/stdout/argv. The four
logic functions are pure and import-clean. Any malformed invocation prints usage to stderr and
exits non-zero — but the four logic functions never raise on string input (a malformed regex is
impossible since patterns are literals).

### 3.2 Exit codes

`0` on success for every subcommand (the *result* is on stdout, not the exit code — the shell
branches on stdout text, mirroring how it branches on `grep` output today). Usage error → `2`.

---

## 4. Shell integration (`check_agents_static.sh`)

### 4.1 Section 3 (lines 108–132) — path references

The inner `while read ref` loop's data source changes from the inline `grep -oE | tr | grep`
pipeline to:
```
cat "$f" | python3 scripts/oversight/agents_static_logic.py extract-path-refs
```
Inside the loop, the five pure guards (http, empty, bare filename, `{template}`, `PROJECT/`) are
replaced by one call:
```
verdict=$(python3 scripts/oversight/agents_static_logic.py filter-path-ref "$ref")
[[ "$verdict" == SKIP ]] && continue
```
**Implementation decision (output-doc exemption):** the filter is called **without** the
`output_docs` argument so an output-doc reference returns `CHECK`, not `SKIP`. The shell then runs
its existing `grep -qx "$OUTPUT_DOCS"` to emit the distinct
`"(output doc — existence not required)"` OK line. Calling the filter *with* output_docs would
SKIP those refs silently and DROP that OK line — a behavior change forbidden by spec §5. So
`filter_path_ref`'s sixth (output-doc) guard exists for unit-test fidelity to the full spec
cascade, but the shell integration deliberately omits the list to preserve the original message.
This keeps the *decision* (the five universal skips) in Python while the output-doc exemption —
which only changes a message, not a skip/check outcome that affects findings — stays a one-line
shell membership test. Verified: original vs refactored script output is byte-identical. The `ref_clean`
recomputation in shell is removed — the function returns the verdict; for the `ok`/`fail`
existence message the shell still needs the cleaned path. **Design decision:** to keep the message
text identical, the shell derives the cleaned path for display with the same `tr|sed|xargs` it
already had (kept solely for the display string), OR `filter-path-ref` prints `CHECK\t<cleaned>` —
**chosen: keep the display-only clean in shell**, because `[[ -e "$ref_clean" ]]` must run on the
cleaned path and duplicating that one transform is display glue, not logic (the *decision* logic is
fully in Python). This honors "shell must not re-implement the logic" — the cleaning kept in shell
is a pure display/path-derivation, identical to argument prep, not a classification branch.

> **Self-review note (R4 boundary):** keeping the one-line `tr|sed|xargs` clean in shell is the
> minimal display-glue needed for the `[[ -e ]]` test and the message. It duplicates the
> *transform* but not the *decision cascade*. An alternative is to have `filter-path-ref` emit the
> cleaned path alongside the verdict; flagged for architect ruling. Default = keep clean in shell.

### 4.2 Section 4 (lines 147–185) — escalation targets

The inner `while read target` source changes from the inline `python3 -c` heredoc to:
```
cat "$f" | python3 scripts/oversight/agents_static_logic.py extract-escalation-targets
```
Inside the loop, lines 153–172 (the three exclusion stages + external check) collapse to:
```
verdict=$(python3 scripts/oversight/agents_static_logic.py classify-token \
    "$target" "$KNOWN_AGENTS_PIPE" "$NON_AGENT_TOKENS" "$KNOWN_LABELS" \
    "$KNOWN_SHORT_AGENTS" "$EXTERNAL_AGENTS")
case "$verdict" in
  SKIP) continue ;;
  EXTERNAL) ok "[$agent_name] → $target (external — lives in consumer projects)"; continue ;;
esac
# CHECK: existence test stays in shell (matches KNOWN_AGENTS membership)
```
- `KNOWN_AGENTS` is currently a newline-separated string; the shell converts to pipe-joined
  (`tr '\n' '|'` with trailing-pipe trim) once per run for the argv, OR passes it newline-joined
  and the CLI splits on newline. **Chosen: pass newline-joined `KNOWN_AGENTS` as-is** is unsafe in
  argv (embedded newlines are fine in a quoted arg but fragile); **pipe-join once** before the loop
  is cleaner. The `KNOWN_SHORT_AGENTS` and `KNOWN_LABELS` definitions (lines 158, 160) move OUT of
  the inner loop to module-load top (they are loop-invariant; currently redefined each iteration —
  no behavior change, minor cleanup).
- The final `grep -qx "$KNOWN_AGENTS" "$target"` existence test (lines 173–177) STAYS in shell:
  it is the `OK: resolves` / `FAIL: no agent file` decision, and it is a set-membership the shell
  already owns against the canonical `KNOWN_AGENTS`. `classify_token` returning `CHECK` is the
  signal to run it. (Spec §R2: `CHECK` = "should be existence-checked against `known_agents`".)

### 4.3 Section 4 — `NON_AGENT_TOKENS` assembly stays in shell

Lines 144–145 assemble `NON_AGENT_TOKENS` by appending `PROJECT_NON_AGENT_TOKENS` from
`config.sh`. This assembly stays in shell (binding 4: the module never sources config.sh); the
assembled string is passed as the `non_agent_tokens` argv. No change to content (spec §5).

### 4.4 Self-static-check constraint

`check_agents_static.sh` references `scripts/oversight/agents_static_logic.py` in backticks? No —
it references it as a bare command path in the `python3 ...` invocation, not a backtick path claim,
so section 3's own path-ref check does not flag it. **Verify:** the new module path must EXIST on
disk (it will, once created) so even if some doc backticks it, the check passes. The script must
still pass `bash scripts/framework/check_agents_static.sh` after modification (no new findings).

---

## 5. Test plan (unit, pure — `tests/oversight/test_agents_static_logic.py`)

Load via `importlib.util.spec_from_file_location` (panel_logic precedent). Cover every AC:

| Test | AC | Function | Assertion |
|---|---|---|---|
| escalation standard | AC1 | extract_escalation_targets | ``"escalates to `architect`"`` → `["architect"]` |
| escalation multiple | AC2 | extract_escalation_targets | invokes + notifies → both, in order |
| escalation verb variants | AC3 | extract_escalation_targets | `escalated to`, `invoked by` both match |
| escalation no-match | AC4/R1 | extract_escalation_targets | bare `` `coder` `` with no verb → not matched by verb; matched only if verb precedes (same as current) |
| classify non-agent | AC5 | classify_token | `human`, `ci` → SKIP |
| classify label | AC6 | classify_token | `needs-human`, `hos-claimed` → SKIP |
| classify hyphen heuristic | AC7 | classify_token | `architect`∈short→CHECK; `mylib`→SKIP; `code-reviewer`→CHECK |
| classify external | AC8 | classify_token | `pm-agent`∈external → EXTERNAL |
| classify anchoring | — | classify_token | `superhuman` (≠`human`) → not SKIP-by-non-agent |
| path skip cases | AC9 | filter_path_ref | http / no-slash / `{...}` / `PROJECT/` / output-doc → SKIP |
| path check case | AC10 | filter_path_ref | `scripts/oversight/panel_logic.py` → CHECK |
| path-ref extraction | OQ-2 | extract_path_refs | extracts backtick paths, drops http, strips backticks |
| purity | R5 | all four | no I/O — pure string→value (implicit by import) |

Shell-integration ACs (AC11, AC12) verified by running `check_agents_static.sh` against the live
agent tree (it already references real + external agents) and by `grep -c 'python3 -c'` = 0.

---

## 6. Affected sign-offs analysis

This is a **refactor with no behavior change** (spec §5 Non-Requirements). The contract of
`check_agents_static.sh` (exit codes, OK/FAIL/WARN lines) is invariant. No prior sign-off is
invalidated. The change is **structural-to-the-module** but **clarifying-to-the-pipeline** (it adds
testability without changing checked behavior). No code was previously approved against a now-changed
contract → no orphaned approvals.

Change classification: **additive** (new module + testability) with a faithful shell substitution.
RISK: LOW. No `## Human Review Required` block required at this tier (no MEDIUM+ design change — the
behavior contract is frozen by spec §5).

---

## 7. Architect review request

Requesting architect review. Specific points for ruling:
1. §4.1 — keep the display-only path `clean` transform in shell vs. have `filter-path-ref` emit the
   cleaned path with the verdict. Default: keep in shell (display glue, not logic).
2. §1.1 — `classify_token` list params as pipe-joined strings (shell-native) vs. `set[str]`.
   Default: pipe-joined strings, normalized at the boundary.

No product questions surfaced. No architecture disputes. No `startup-artifact-gap` (the inline
Python predates this spec and #314 is the policy driver that authorized the extraction).
