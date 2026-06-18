# SPEC-337: Move suspension gate regex and audit-event JSON building to Python

**Status:** Draft — for architect review
**Issue:** #337
**Policy:** #314 — prefer Python for logic, shell for launch; testability is a code review criterion
**Date:** 2026-06-17

---

## 1. Problem statement

`scripts/oversight/gates/check_suspension.sh` contains two pieces of correctness-critical logic that currently live in bash:

1. **The gate-suspension regex** (`is_suspended()`, line 39) — validates that a line in `contract/gate-suspension.md` matches the active-suspension grammar `^SUSPENDED:<gate>([pinned]|review-by:YYYY-MM-DD)*$`. This regex is the sole enforcement point for whether a gate is bypassed at runtime. A mismatch between this bash regex and the Python regex in `suspension_manager.py` caused HOS#105: the bash `is_suspended()` used an old end-anchored bare match that rejected flagged forms (`[pinned]`, `review-by:`) the manager correctly treated as active, so a suspension the manager reported as ACTIVE was silently IGNORED and the gate kept running.

2. **The audit-event JSON builder** (`_emit_suspension_audit()`, lines 46–56) — constructs and appends the `gate-suspended` event to `audit/oversight-log.jsonl`. The JSON is built by `printf` with a manual apostrophe-escape on the `authorized_by` field (`${authorized_by//\"/\'}`). This is the primary audit trail for a bypassed safety gate and must conform to the `gate-suspended` event schema in `OVERSIGHT-CONTRACT.md §6a`.

Both items are difficult to unit test in bash. The grammar divergence that caused HOS#105 went undetected precisely because the two parsers lived in different languages with no shared test surface.

`suspension_manager.py` already exists at `scripts/oversight/suspension_manager.py` and already owns `_SUSPENDED_RE` (the canonical Python regex) and the `emit_audit()` function. The fix is to consolidate: the bash helper should delegate to the Python module rather than re-implementing both in shell.

---

## 2. Scope

### What moves

| Current location | Current implementation | Target |
|---|---|---|
| `check_suspension.sh` `is_suspended()` body | bash `grep -Eq` with inline regex | delegates to `suspension_manager.py --is-suspended <gate>` (already exists; see §3 below) |
| `check_suspension.sh` `_emit_suspension_audit()` | `printf` JSON + `>>` append | delegates to a new `--emit-audit` entry point in `suspension_manager.py` |

### What stays in shell

- `check_suspension.sh` itself remains as the sourced bash helper that gate scripts call. Its external interface (`source check_suspension.sh` / `is_suspended "gate"` / `print_suspended "gate"`) does not change.
- Gate scripts continue to `source check_suspension.sh` and call `is_suspended` and `print_suspended` as today. No gate script changes are required.
- `suspension_manager.py`'s existing CLI surface (`--census`, `--check`, `--auto-remove`, `--is-suspended`) is unchanged.

---

## 3. Current behavior to preserve exactly

### 3a. `is_suspended(gate)`

The function returns exit 0 (suspended) or 1 (not suspended) for a given gate name. The active-suspension grammar it must match is:

```
^SUSPENDED:[whitespace]*<gate>([whitespace]+\[pinned\]|[whitespace]+review-by:[whitespace]*YYYY-MM-DD)*[whitespace]*$
```

This grammar is already canonically expressed as `_SUSPENDED_RE` in `suspension_manager.py` (line 57–60). The `--is-suspended <gate>` entry point already exists in `suspension_manager.py` (`cmd_is_suspended`, line 273–283) and returns exit 0/1 correctly.

**Current bash delegation path (already exists, check_suspension.sh line 39):** the comment on line 33 already notes "Grammar MUST stay in sync with `_SUSPENDED_RE` in `suspension_manager.py`" — this spec makes the sync automatic by removing the bash copy.

### 3b. `_emit_suspension_audit(gate, authorized_by)`

Appends exactly one JSON line to `audit/oversight-log.jsonl` when the file's parent directory exists. Current output:

```json
{"event":"gate-suspended","gate":"<gate>","authorized_by":"<authorized_by>","timestamp":"<ISO-8601 UTC>"}
```

This must conform to the `gate-suspended` schema in `OVERSIGHT-CONTRACT.md §6a`. The contract specifies required fields: `gate`, `step`, `authorized_by`, `suspension_file`, `reason_category`. The current bash implementation emits only `gate`, `authorized_by`, and `timestamp` — it is missing `step`, `suspension_file`, and `reason_category`. This spec does not require filling those gaps (that would be new behavior). The Python implementation must emit at minimum the same fields the bash implementation currently emits.

**Open question for architect (OQ-1):** Should the Python `--emit-audit` entry point fill in the missing fields (`step`, `suspension_file`, `reason_category`) that the contract schema specifies but the bash implementation omits? Filling them would make the audit event more complete but would be a behavior change. This spec treats it as out of scope unless the architect directs otherwise.

### 3c. `print_suspended(gate)`

This function prints the human-readable suspension notice and then calls `_emit_suspension_audit`. It currently reads `authorized_by` from `gate-suspension.md` by grepping for the `Authorized by:` line. This logic stays in bash — only the `_emit_suspension_audit` call within it is redirected to Python.

---

## 4. Requirements

**R1 — Canonical regex in one place.** `is_suspended()` in `check_suspension.sh` must use `suspension_manager.py --is-suspended <gate>` (exit 0 = suspended, exit 1 = not suspended) rather than a separate bash `grep -Eq` expression. The bash regex on line 39 is removed.

**R2 — Audit-event emission in Python.** `_emit_suspension_audit()` in `check_suspension.sh` must delegate to `suspension_manager.py` for JSON construction and file append. The bash `printf` JSON builder on lines 53–55 is removed.

**R3 — New `--emit-audit` entry point.** `suspension_manager.py` gains a new CLI flag `--emit-audit` (or equivalent) that accepts `--gate <name>` and `--authorized-by <value>` and appends the `gate-suspended` event to `audit/oversight-log.jsonl` using the existing `emit_audit()` function. It must behave identically to the current bash: it is a no-op when the `audit/` directory does not exist (matches current `_emit_suspension_audit` line 51).

**R4 — Unit-testable without a live gate run.** Both `_SUSPENDED_RE` matching and `emit_audit()` must be exercisable from a Python unit test with no subprocess, no git repo, and no filesystem side effects beyond a tmp dir. This is already largely true for `_SUSPENDED_RE`; the `--emit-audit` path must be equally testable.

**R5 — External interface unchanged.** Gate scripts that call `is_suspended "gate"` and `print_suspended "gate"` must require no changes. The shell function signatures, exit codes, and stdout output are unchanged.

**R6 — Fail-closed on Python unavailability.** If `python3` is not found, `is_suspended` must fail such that the gate does NOT silently pass (i.e., it does not return exit 0 as though the gate were suspended). The architect should specify whether this means the gate fails hard (exit 1 from `is_suspended`, causing the gate to run normally) or exits with an error. Failing open (treating unavailable Python as "suspended") is explicitly not permitted.

---

## 5. Non-requirements

- This change does not alter the suspension grammar or add new grammar features.
- This change does not fill in the missing `step`, `suspension_file`, or `reason_category` fields in the bash-emitted audit event (see OQ-1 above — that is a separate issue if desired).
- This change does not modify the `--census`, `--check`, or `--auto-remove` behavior of `suspension_manager.py`.
- This change does not affect how gate scripts are invoked or how their results are recorded.
- No new features. No behavior changes beyond removing the regex duplication.

---

## 6. Open questions for architect

**OQ-1 (audit schema completeness):** The `gate-suspended` contract schema (OVERSIGHT-CONTRACT.md §6a) includes `step`, `suspension_file`, and `reason_category` fields that the current bash `_emit_suspension_audit` does not emit. When the Python `--emit-audit` path is built, should it fill those fields (additive improvement) or match the bash behavior exactly (pure parity)? The architect should rule before the coder implements.

**OQ-2 (module placement):** Should `--emit-audit` live in the existing `suspension_manager.py`, or should the regex and audit logic be extracted into a new `suspension_logic.py` module that both `check_suspension.sh` and `suspension_manager.py` import? The issue title says "suspension_logic.py" but the existing module is a reasonable home. Architect decision.

**OQ-3 (Python invocation from bash):** The bash `is_suspended()` function is called on every gate invocation. The architect should confirm that spawning a `python3 suspension_manager.py --is-suspended` subprocess per gate invocation is acceptable at runtime, or whether a different delegation mechanism (e.g., a shared compiled regex, or caching the result) is preferred.
