# Technical Design — Issue #332: Panel Triage Floor + SQC Sampling → `panel_logic.py`

**Document type:** Technical design (contract for the coder)
**Status:** For architect review
**Issue / Spec:** #332 / `docs/specs/SPEC-332-panel-triage-floor-python.md`
**Architect ruling:** GO (bindings reproduced in §0)
**Depends on:** SPEC-376 (seeded `panel_logic.py`)
**Blocks:** SPEC-333 (further panel logic extraction)
**Author:** technical-design
**Date:** 2026-06-17

---

## 0. Architect bindings (governing)

1. **EXTEND** `scripts/oversight/panel_logic.py` — do NOT create a new file.
2. `max_risk` / `rank` bash helpers **STAY in shell**. Only the floor rules and the
   SQC hash move to Python.
3. Triage-floor patterns are **HARDCODED module constants** — not configurable. A
   behavior change requires a separate spec + product gate.
4. **No subpackage** — single flat `panel_logic.py`.
5. Functions to add:
   - `compute_triage_floor(changed_files: list[str], added_lines: int) -> str`
   - `compute_sqc_sample(head_sha: str, salt: str, tier: str, sample_rates: dict) -> dict`
6. **Reproduce the shell's existing logic byte-for-byte** — parity refactor, no
   behavior change (Spec §5).
7. **Unit-testable without a live panel run** — synthetic inputs, no subprocess/IO.
8. Add `--triage-floor` and `--sqc-sample` subcommands to the existing CLI shim.

This design is a contract: it specifies *what* each function and shell call must do.
It does not contain the implementation.

---

## 1. Data model — module constants

All triage-floor patterns become **module-level constants** (binding 3). They are the
single source of truth, transcribed verbatim from `run_panel.sh` `det_floor`
(lines 268–272) so the case-insensitive `grep -qiE` behavior is reproduced exactly.

| Constant | Type | Value (verbatim from shell) | Floor it sets |
|---|---|---|---|
| `_SRC_EXT_RE` | compiled regex (IGNORECASE) | `\.(ts\|tsx\|js\|jsx\|py\|go\|rb\|java\|cs\|php\|rs\|sh)$` | MEDIUM |
| `_DEP_MANIFEST_RE` | compiled regex (IGNORECASE) | `(package\.json\|package-lock\|yarn\.lock\|pnpm-lock\|requirements\.txt\|go\.mod\|Gemfile\|Cargo\.toml\|composer\.json)` | MEDIUM |
| `_HIGH_PATH_RE` | compiled regex (IGNORECASE) | `(auth\|login\|session\|middleware\|password\|token\|crypto\|secret\|/api/\|routes?/\|migrations?/\|schema\|/db/\|sql)` | HIGH |
| `_CRITICAL_PATH_RE` | compiled regex (IGNORECASE) | `(payment\|billing\|stripe\|checkout\|/delete\|destroy\|drop_)` | CRITICAL |
| `_DEFAULT_SIZE_FLOOR` | int | `500` | (used as default arg only) |
| `_TIER_RANK` | dict | `{"LOW":0,"MEDIUM":1,"HIGH":2,"CRITICAL":3}` | ranking for the floor ratchet |

**Invariants:**
- Patterns are matched **case-insensitively** (the shell uses `grep -qiE`). The compiled
  regexes MUST carry `re.IGNORECASE`.
- Patterns are matched against the **whole newline-joined file blob**, mirroring the
  shell's `echo "$files" | grep -qiE`. A match anywhere in any path triggers the rule.
- These constants MUST NOT read any environment variable or config file. Binding 3:
  changing them is a behavior change requiring a new spec.
- A comment block above the constants MUST direct a consumer who wants project-specific
  overrides to the **PROJECT region of the relevant agent**, not to editing these
  constants (Spec OQ-2 resolution).

---

## 2. `compute_triage_floor(changed_files, added_lines, size_floor=_DEFAULT_SIZE_FLOOR) -> str`

### Signature
```python
def compute_triage_floor(
    changed_files: list[str],
    added_lines: int,
    size_floor: int = _DEFAULT_SIZE_FLOOR,
) -> str:
```

> **Note on the binding-5 signature.** Binding 5 lists
> `compute_triage_floor(changed_files: list[str], added_lines: int)`. R1 of the spec
> additionally requires `SIZE_FLOOR` to be a **parameter with a default**, so tests can
> exercise the 500-line boundary (AC4). The design honors both: a third
> keyword-only-by-default parameter `size_floor` is **additive** — every binding-5 call
> site (positional `changed_files, added_lines`) is unaffected. This is an *additive*
> change, flagged in §9.

### Inputs
- `changed_files: list[str]` — list of changed file paths. The shell currently holds
  them newline-separated in `$CHANGED_FILES`; the **CLI shim** (not this function) is
  responsible for splitting on newlines. This pure function receives a list. Empty
  strings and blank lines, if present, are harmless (they match nothing).
- `added_lines: int` — count of added lines in the diff (shell `$ADDED`).
- `size_floor: int` — added-line threshold that ratchets to MEDIUM. Default `500`.

### Output
- A risk-tier string: exactly one of `"LOW"`, `"MEDIUM"`, `"HIGH"`, `"CRITICAL"`.

### Algorithm (byte-for-byte parity with `det_floor`, binding 6)

Reproduce the shell ratchet exactly. The shell joins the file list and runs five
sequential checks, each of which can only **raise** the floor (`max_risk` never lowers):

```
files_blob = "\n".join(changed_files)
level = "LOW"
if _SRC_EXT_RE.search(files_blob):       level = "MEDIUM"     # shell line 268
if _DEP_MANIFEST_RE.search(files_blob):  level = "MEDIUM"     # shell line 269
if added_lines > size_floor:             level = max(level, "MEDIUM")   # shell line 270
if _HIGH_PATH_RE.search(files_blob):     level = max(level, "HIGH")     # shell line 271
if _CRITICAL_PATH_RE.search(files_blob): level = max(level, "CRITICAL") # shell line 272
return level
```

where `max(a, b)` is by `_TIER_RANK` (a private `_max_tier(a, b)` helper reproduces the
shell `max_risk`). The first two assignments set MEDIUM unconditionally (matching the
shell's bare `level="MEDIUM"`), which is safe because they precede every higher rule and
each later rule only ratchets up.

**Boundary parity (AC4):** the shell uses `(( added > SIZE_FLOOR ))` — strictly greater
than. `added_lines == size_floor` does **not** trip MEDIUM; `added_lines == size_floor+1`
does. Reproduce `>` exactly, not `>=`.

### Boundaries — what this function MUST honor / MUST NOT do
- MUST be pure: no subprocess, file, or network I/O; MUST NOT read env or config (R4).
- MUST NOT mutate inputs.
- MUST NOT add, remove, or reorder patterns (Spec §5 / binding 6) — the order
  src → dep → size → high → critical is load-bearing only insofar as the ratchet is
  monotonic; preserve it to match the shell line-for-line.
- MUST return only the floor. It MUST NOT combine with the author trailer or Haiku
  output — `max_risk` for those stays in shell (binding 2).

---

## 3. `compute_sqc_sample(head_sha, salt, tier, sample_rates) -> dict`

### Signature
```python
def compute_sqc_sample(
    head_sha: str,
    salt: str,
    tier: str,
    sample_rates: dict,
) -> dict:
```

### Inputs
- `head_sha: str` — the PR head commit SHA (shell `$HEAD_SHA`).
- `salt: str` — the secret audit salt (shell `$SALT`), already resolved by the shell
  (env var / file / freshly minted). This function only consumes it (Spec §5).
- `tier: str` — current risk tier (`"LOW" | "MEDIUM" | "HIGH" | "CRITICAL"`).
- `sample_rates: dict` — tier→percent map. Per binding 5 the function takes a single
  `sample_rates` dict rather than separate `sample_low`/`sample_med` ints (R2 phrasing).
  Expected keys `"LOW"` and `"MEDIUM"` (the shell passes `SAMPLE_LOW`/`SAMPLE_MED`).
  Missing keys default to rate `0` (→ not sampled), which is the safe parity behavior
  (a `RATE=0` tier is never sampled in the shell).

### Output — a `dict` with exactly these keys (binding 5 / R2):
```python
{"sampled": bool, "roll": int, "rate": int}
```
- `sampled` — whether the PR is selected for the extra red-team adversary pass.
- `roll` — the computed roll value `0–99` (or `-1` when no roll is performed, mirroring
  the shell's `ROLL=-1` initial value for HIGH/CRITICAL / rate-0 tiers — see below).
- `rate` — the applicable sample rate for the tier (`0` for HIGH/CRITICAL).

### Algorithm (byte-for-byte parity with shell lines 326–330, binding 6)

```
rate = sample_rates.get(tier, 0)          # shell: case RISK in LOW/MEDIUM/*  (line 326)
                                          #   only LOW & MEDIUM have nonzero rates
if rate <= 0:                             # shell: HIGH/CRITICAL -> RATE=0, block skipped
    return {"sampled": False, "roll": -1, "rate": 0}

digest = hashlib.sha256((head_sha + salt).encode()).hexdigest()   # shell line 328
roll = int(digest[:8], 16) % 100          # shell: cut -c1-8 ; 0x$HEX % 100  (lines 328-329)
sampled = roll < rate                     # shell: (( ROLL < RATE )) && SAMPLED=1  (line 330)
return {"sampled": sampled, "roll": roll, "rate": rate}
```

**Hash parity (R2):** the shell computes `printf '%s' "${HEAD_SHA}${SALT}" | sha256sum`
(or `shasum -a 256`), takes hex chars 1–8, interprets as hex, `% 100`. Python:
`hashlib.sha256((head_sha + salt).encode())`, `.hexdigest()[:8]`, `int(..., 16) % 100`.
`printf '%s'` emits no trailing newline, so `.encode()` of the concatenation (no newline)
matches the bytes hashed by the shell. The concatenation order is `head_sha + salt`
(HEAD_SHA first), matching `${HEAD_SHA}${SALT}`.

**HIGH/CRITICAL parity (AC8):** these tiers are absent from `sample_rates` (the shell
sets `RATE=0` for them in the `*)` case) → `rate=0` → returns
`{"sampled": False, "roll": -1, "rate": 0}`. The function does NOT make HIGH/CRITICAL
fire the full roster; that is a separate shell path (Spec §2, binding for R2). This
function only reports `rate=0, sampled=False`.

> **`roll` value for the non-sampled-tier case.** Binding 5 says HIGH/CRITICAL
> "rate=0 → always sampled". The spec body (R2 / AC8) and the existing shell are
> authoritative and say the **opposite**: HIGH/CRITICAL return `sampled=False, rate=0`
> *from this function* because they are sampled at 100% by a **separate shell path**,
> not by this function. The shell at line 326 sets `RATE=0` for HIGH/CRITICAL and the
> SQC roll block is skipped; the always-on adversary pass for HIGH+ is added at
> `run_panel.sh` line 356 (`ROSTER+=("codex:adversary")`), independent of SQC.
> This design follows the spec/shell (AC8: `sampled=False, rate=0`) to preserve
> **byte-for-byte parity (binding 6)**, which governs. The binding-5 shorthand
> "always sampled" describes the *system* outcome (HIGH+ always gets the adversary),
> not this function's return — surfaced as a clarifying note for the architect, §9.

### Boundaries
- MUST be pure: `hashlib` only; no file/subprocess/network/env (R4). The salt is an
  argument, never read from disk here (Spec §5).
- MUST NOT write the sample-log; that stays in shell using the returned `roll`/`sampled`
  (Spec §5, out of scope).
- MUST NOT mint or persist the salt (Spec out of scope).

---

## 4. CLI shim contract (binding 8)

The existing `main(argv)` reads the arbiter object on stdin and corroboration-ranks it
(SPEC-376). That default path is invoked by `run_panel.sh` line 505 as
`python3 panel_logic.py --raw <file>` with **no subcommand**. Back-compat MUST be
preserved.

**Design:** convert `main()` to use `argparse` subparsers (`add_subparsers(dest="cmd")`)
with the SPEC-376 behavior remaining the **default when no subcommand is given**, so the
existing `--raw` invocation is byte-for-byte unaffected.

### 4.1 `--triage-floor` subcommand
- **Invocation:** `python3 panel_logic.py triage-floor --added-lines N [--size-floor M]`
  with the newline-separated file list on **stdin** (the shell already holds the list in
  `$CHANGED_FILES`).
- **Action:** read stdin, `splitlines()`, call
  `compute_triage_floor(files, added_lines, size_floor)`.
- **stdout:** the tier string followed by a newline (e.g. `MEDIUM\n`). Exactly the value
  the shell would have produced from `det_floor`, so `FLOOR="$(... )"` captures it
  unchanged.
- **Exit:** `0`.

### 4.2 `--sqc-sample` subcommand
- **Invocation:**
  `python3 panel_logic.py sqc-sample --head-sha SHA --salt SALT --tier TIER --sample-low L --sample-med M`
- **Action:** build `sample_rates = {"LOW": sample_low, "MEDIUM": sample_med}`, call
  `compute_sqc_sample(head_sha, salt, tier, sample_rates)`.
- **stdout:** the result as compact JSON: `{"sampled": <bool>, "roll": <int>, "rate": <int>}`.
  The shell parses it with `jq` (already a dependency).
- **Exit:** `0`.

> **Subcommand name vs. flag.** Binding 8 says "add a `--triage-floor` and `--sqc-sample`
> subcommand". `argparse` subcommands are positional tokens; this design uses the
> positional forms `triage-floor` / `sqc-sample`. If the architect requires the literal
> `--`-prefixed spellings, they can be added as aliases. Surfaced in §9 (clarifying).

### Failure posture
- The triage-floor and sqc-sample subcommands compute deterministic risk inputs that
  **gate reviewer staffing** (Spec §1: a bug could under-staff a HIGH PR or suppress the
  audit). Unlike the SPEC-376 ranking (an enhancement that fails open), these MUST fail
  **loud**: on malformed args / bad input, exit non-zero so the shell's
  `set -euo pipefail` surfaces it rather than silently defaulting to LOW. (The shell keeps
  its own fallback only where it already has one — see §5.)

---

## 5. Shell integration — `run_panel.sh` (R3 / AC10)

### 5.1 Resolve the module path (reuse the existing SPEC-376 pattern, lines 501–502)
The script already computes `$PANEL_LOGIC`. Reuse that same resolved variable for the
new calls; do not recompute it.

### 5.2 Replace `det_floor` (lines 266–276)
- **Remove** the entire `det_floor()` bash function (lines 266–274).
- **Replace** the call at line 276:
  ```
  FLOOR="$(det_floor "$CHANGED_FILES" "$ADDED")"
  ```
  with a call to the subcommand, passing the file list on stdin and `$ADDED` /
  `$SIZE_FLOOR` as flags:
  ```
  FLOOR="$(printf '%s' "$CHANGED_FILES" | python3 "$PANEL_LOGIC" triage-floor \
            --added-lines "$ADDED" --size-floor "$SIZE_FLOOR")"
  ```
- The downstream `max_risk "$FLOOR" "$AUTHOR_RISK"` (line 281) and the Haiku combination
  (line 302) are **unchanged** — they stay in shell (binding 2). `$SIZE_FLOOR` (shell
  line 69) is still defined and is now passed through to Python instead of being read by
  the removed function.

### 5.3 Replace the SQC hash/modulo block (lines 326–330)
- **Keep** in shell (Spec §5, out of scope): the salt acquisition (lines 318–325), the
  `sha256()` helper *only if still used elsewhere* — it is not, so it may be removed
  (it exists solely for this block), the sample-log append (lines 331–334), and the
  selected/not-selected `info` lines (335–336).
- **Replace** the rate selection + hash + roll (lines 326–330):
  ```
  case "$RISK" in LOW) RATE=$SAMPLE_LOW ;; MEDIUM) RATE=$SAMPLE_MED ;; *) RATE=0 ;; esac
  if (( RATE > 0 )); then
    HEX=$(printf '%s' "${HEAD_SHA}${SALT}" | sha256 | cut -c1-8)
    ROLL=$(( 0x$HEX % 100 ))
    (( ROLL < RATE )) && SAMPLED=1
    ...
  ```
  with a single Python call whose JSON result feeds the existing `RATE`/`ROLL`/`SAMPLED`
  variables:
  ```
  SQC_JSON="$(python3 "$PANEL_LOGIC" sqc-sample \
              --head-sha "$HEAD_SHA" --salt "$SALT" --tier "$RISK" \
              --sample-low "$SAMPLE_LOW" --sample-med "$SAMPLE_MED")"
  RATE=$(printf '%s' "$SQC_JSON" | jq -r '.rate')
  ROLL=$(printf '%s' "$SQC_JSON" | jq -r '.roll')
  SAMPLED=$(printf '%s' "$SQC_JSON" | jq -r 'if .sampled then 1 else 0 end')
  ```
- The `if (( RATE > 0 ))` guard around the **sample-log append + info lines** stays in
  shell, exactly as today, so a rate-0 tier writes no log line (parity). The Python call
  itself is cheap and may run unconditionally inside the existing `if (( DO_SAMPLE ))`
  block; the `RATE > 0` guard then wraps only the log/info, as before.
- The `sha256()` shell helper (line 314) is **removed** (it has no other caller).

### 5.4 No logic duplication (AC10)
After this change, `run_panel.sh` contains **no** triage-floor pattern regexes and **no**
SHA256/modulo arithmetic. Both live only in `panel_logic.py`.

---

## 6. Component map

| Component | Location | Responsibility | MUST NOT |
|---|---|---|---|
| `_SRC_EXT_RE` … `_CRITICAL_PATH_RE`, `_DEFAULT_SIZE_FLOOR`, `_TIER_RANK` | `panel_logic.py` (new constants) | Hardcoded triage patterns + size floor + tier ranking | be env/config-driven (binding 3) |
| `_max_tier(a, b)` | `panel_logic.py` (new private helper) | Tier ratchet (reproduces shell `max_risk`) | lower a tier |
| `compute_triage_floor(...)` | `panel_logic.py` (new, pure) | Deterministic floor from files + added lines | combine author/Haiku risk; do I/O |
| `compute_sqc_sample(...)` | `panel_logic.py` (new, pure) | Salted SHA256 roll vs. tier rate | mint/persist salt; write sample-log; do I/O |
| `triage-floor` / `sqc-sample` subcommands | `panel_logic.py` `main()` (extended) | argv/stdin/stdout glue; the only place doing I/O | embed decision logic |
| default (no-subcommand) `main()` path | `panel_logic.py` | SPEC-376 corroboration ranking — unchanged | regress back-compat |
| `det_floor` removal + Python call | `run_panel.sh` lines 266–276 | Floor decision now delegated | re-implement patterns |
| SQC block rewrite | `run_panel.sh` lines 314, 326–330 | Roll now delegated | re-implement hash/modulo |
| salt acquire / sample-log / info lines | `run_panel.sh` lines 318–325, 331–336 | Stay in shell (Spec §5) | move to Python |

---

## 7. Test plan (extends `tests/oversight/test_panel_logic.py`, R4)

All new tests import the module via the existing `importlib` harness (no subprocess).
Pure functions only — no live panel.

| Test | Maps to | Assertion |
|---|---|---|
| `test_triage_floor_source_file_medium` | AC1 | `["src/views.py"], 10` → `"MEDIUM"` |
| `test_triage_floor_auth_high` | AC2 | `["app/auth/login.py"], 10` → `"HIGH"` |
| `test_triage_floor_payment_critical` | AC3 | `["billing/stripe.py"], 10` → `"CRITICAL"` |
| `test_triage_floor_size_boundary` | AC4 | `["README.md"], 501, size_floor=500` → `"MEDIUM"`; `500` → `"LOW"` |
| `test_triage_floor_multi_file_max` | AC5 | `["README.md","app/auth/session.py"], 5` → `"HIGH"` |
| `test_triage_floor_default_low` | parity | `["README.md"], 5` → `"LOW"` |
| `test_triage_floor_dep_manifest_medium` | R1 | `["package-lock.json"], 1` → `"MEDIUM"` |
| `test_triage_floor_case_insensitive` | parity (`-qiE`) | `["APP/AUTH/Login.PY"], 1` → `"HIGH"` |
| `test_triage_floor_is_pure` | R4 | input list not mutated; deterministic |
| `test_sqc_reproducible` | AC6 | same args → identical `sampled`/`roll` across calls |
| `test_sqc_threshold_boundary` | AC7 | construct a SHA whose roll is 24/25 vs `sample_low=25`: `<` selected, `==` not |
| `test_sqc_high_returns_rate_zero` | AC8 | `tier="HIGH"` → `{"sampled":False,"roll":-1,"rate":0}` |
| `test_sqc_critical_returns_rate_zero` | AC8 | `tier="CRITICAL"` → `rate=0, sampled=False` |
| `test_sqc_hash_matches_known_vector` | R2 / binding 6 | hardcode `sha256("abc"+"salt")[:8] % 100`; assert `roll` equals it |
| `test_sqc_is_pure` | R4 | no file written; deterministic |

For AC7 the test computes the expected roll directly with `hashlib` (the same vector the
function uses), then chooses `sample_low` one above / equal to that roll — this proves the
`<` (strict) comparison without depending on a magic SHA.

**Parity guard:** one test (`test_sqc_hash_matches_known_vector`) pins the exact byte
recipe (`head_sha + salt`, first 8 hex chars, `% 100`) so a future change to the hash
input is caught. This is the byte-for-byte parity anchor (binding 6).

---

## 8. Verification gates (from the task)

1. `bash -n scripts/run_panel.sh` — syntax check passes.
2. `./scripts/framework/run_tests_inner_loop.sh` — all panel_logic tests pass.
3. `bash scripts/framework/check_agents_static.sh` — agents static check clean.

---

## 9. HOS self-flag

**RISK:** LOW
**CONFIDENCE:** HIGH
**BLAST RADIUS:** `scripts/oversight/panel_logic.py` (additive), `scripts/run_panel.sh`
(triage + SQC blocks), `tests/oversight/test_panel_logic.py` (additive). The triage floor
and SQC sample gate reviewer staffing, so a parity regression could mis-staff a panel —
but this is a pure refactor with a byte-for-byte parity test anchor and no behavior change
(Spec §5).

**Change classification:** `additive` (two new pure functions + two new subcommands + new
constants; SPEC-376 default path and the shell's salt/log/roster logic are preserved).
No `structural` change — no module split (binding 4), no schema change, no new behavior.

### Human Review Required
- **Clarifying — binding 5 vs. spec/shell on HIGH/CRITICAL (§3):** binding 5 says
  "HIGH/CRITICAL rate=0 → always sampled"; the spec (AC8) and existing shell return
  `sampled=False, rate=0` from this function (the always-on adversary pass is a separate
  shell path). Design follows the spec/shell to preserve byte-for-byte parity (binding 6,
  which governs). **Confirm this reading.**
- **Clarifying — `size_floor` parameter (§2):** added as an additive default arg to
  satisfy R1/AC4 while keeping binding-5's positional signature intact. **Confirm.**
- **Clarifying — subcommand spelling (§4):** `argparse` positional `triage-floor` /
  `sqc-sample` rather than literal `--triage-floor` flags. **Confirm or request the
  flag spelling.**

No `structural` items → no pre-write human escalation required; the three clarifying
items are flagged for the architect's review of this design before the coder proceeds.
