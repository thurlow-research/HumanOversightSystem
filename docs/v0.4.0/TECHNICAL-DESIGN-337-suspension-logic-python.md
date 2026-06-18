# Technical Design — SPEC-337: Suspension gate logic in Python

**Spec:** `docs/specs/SPEC-337-suspension-logic-python.md`
**Issue:** #337
**Status:** For implementation (architect bindings resolved OQ-1/OQ-2/OQ-3)
**Date:** 2026-06-17

---

## 1. Summary

`scripts/oversight/gates/check_suspension.sh` currently re-implements two pieces
of correctness-critical logic that `scripts/oversight/suspension_manager.py`
already owns: the active-suspension regex and the `gate-suspended` audit-event
builder. The bash copy of the regex diverged from the Python canonical
(`_SUSPENDED_RE`) and caused HOS#105. This design makes Python authoritative:
the bash helper delegates both jobs to `suspension_manager.py`, and the bash
regex copy is deleted.

This is a **structural** change to a safety-relevant control path (gate
suspension) but it is **behavior-preserving by contract** — same exit codes,
same audit JSON, same external shell interface.

---

## 2. Architect bindings (govern this design)

1. EXTEND `suspension_manager.py`. Do NOT create `suspension_logic.py`. (Resolves OQ-2.)
2. Audit schema PARITY ONLY: emit exactly `{event, gate, authorized_by, timestamp}`.
   The 3 contract fields (`step`, `suspension_file`, `reason_category`) are OUT
   OF SCOPE; a follow-up issue tracks them. (Resolves OQ-1.)
3. Fail-safe on Python unavailability: `is_suspended` returns exit 1 (gate runs)
   if `python3` is absent or errors. Exit 0 (gate skipped) on Python failure is
   FORBIDDEN. Print a stderr diagnostic on delegation failure. (Resolves R6.)
4. Per-invocation subprocess is acceptable — no caching, no compiled-regex side
   channel. (Resolves OQ-3.)
5. `--emit-audit` preserves the existing guard: no-op when `audit/` is absent.
6. Remove the bash regex copy in `check_suspension.sh` once Python is authoritative.

---

## 3. Contract — `suspension_manager.py`

### 3a. `--is-suspended <gate>` (already exists, unchanged)

`cmd_is_suspended(gate)` returns `0` if the gate has an active suspension line in
`contract/gate-suspension.md`, `1` otherwise (including when the file is absent).
No change required. The bash helper now invokes this instead of its own regex.

### 3b. New entry point: `--emit-audit`

**CLI surface (additive — does not touch `--census`/`--check`/`--auto-remove`/`--is-suspended`):**

- `--emit-audit` (flag) — selects the emit-audit action.
- `--gate <name>` (string) — the suspended gate name. Required with `--emit-audit`.
- `--authorized-by <value>` (string) — the authorizer string from the suspension
  record. Optional; defaults to `"unknown"` to match the bash default
  (`${authorized_by:-unknown}`).

**Behavior:**

- Constructs the event dict `{"event": "gate-suspended", "gate": <gate>,
  "authorized_by": <authorized_by>}` and passes it to the existing `emit_audit()`.
- `emit_audit()` appends `"timestamp"` last via `{**event, "timestamp": _now()}`,
  yielding key order `event, gate, authorized_by, timestamp` — **byte-identical
  field set and order** to the current bash `printf`.
- `emit_audit()` already guards on `Path("audit").is_dir()`; absent `audit/` →
  no-op (binding 5 / R3 satisfied). The CWD-relative `audit/` check matches the
  bash repo-root resolution because gate scripts run from repo root.
- Returns exit 0 unconditionally (emission is best-effort, like the bash `|| true`).

**Algorithm (new helper `cmd_emit_audit`):**

```
cmd_emit_audit(gate, authorized_by):
    emit_audit({"event": "gate-suspended",
                "gate": gate,
                "authorized_by": authorized_by or "unknown"})
    return 0
```

No new escaping logic is needed: `json.dumps` (inside `emit_audit`) correctly
escapes quotes in `authorized_by`. This is strictly more correct than the bash
apostrophe-swap (`${authorized_by//\"/\'}`), but produces the same field set;
the bash swap was a workaround for hand-built JSON and is dropped with the
printf builder. (Edge note: an `authorized_by` containing a literal `"` will now
serialize as `\"` rather than be mangled to `'`. This is a more-faithful audit
record, not a behavior regression — the field still round-trips as valid JSON.)

### 3c. Argument parsing

`main()` gains `--emit-audit` / `--gate` / `--authorized-by`. The point-query
dispatch block (currently the `--is-suspended` early return) gains a parallel
early return for `--emit-audit`, placed BEFORE the `susp_path.exists()` guard so
emit-audit never requires the suspension file to exist (the gate already knows it
is suspended by the time it emits).

---

## 4. Contract — `check_suspension.sh`

### 4a. Python resolution

A single resolver near the top of the file:

- `_SUSP_MGR` = `<dir of check_suspension.sh>/../suspension_manager.py`
  (i.e. `scripts/oversight/suspension_manager.py`).
- Python interpreter = `${OVERSIGHT_PYTHON:-python3}`, matching the existing
  convention in `secret_scan.sh` / `run_validators.sh`. `OVERSIGHT_PYTHON` is set
  by `ensure_venv.sh` when a venv exists; bare `python3` otherwise.

### 4b. `is_suspended(gate)` — delegate (R1, binding 3/6)

```
is_suspended(gate):
    if interpreter not found (command -v fails) → stderr diagnostic; return 1
    run: "$PY" "$_SUSP_MGR" --is-suspended "$gate"
    rc = $?
    rc == 0 → return 0   # suspended
    rc == 1 → return 1   # not suspended
    rc anything else (python error, traceback, missing module) →
        stderr diagnostic; return 1   # FAIL-CLOSED: gate runs
```

Critical fail-safe detail: only an explicit `0` from the manager means
"suspended/skip the gate". Any other outcome (interpreter missing, file IO error,
unexpected exit code) returns 1 so the gate runs. Exit 0 on Python failure is
forbidden (binding 3). The bash regex on lines 33–40 is deleted.

The `_find_suspension_file` / `_SUSPENSION_FILE` plumbing in the bash file is no
longer needed by `is_suspended` (the manager resolves the file itself via its
repo-relative `SUSPENSION_FILE`). `print_suspended` still greps the suspension
file for `Authorized by:`, so the file-location helper is retained for that path.
The manager resolves `contract/gate-suspension.md` relative to CWD, which is repo
root for gate runs — consistent with how `--is-suspended` is already used by
`run_gates.sh`.

### 4c. `_emit_suspension_audit(gate, authorized_by)` — delegate (R2)

```
_emit_suspension_audit(gate, authorized_by):
    if interpreter not found → return 0   # emission is best-effort
    "$PY" "$_SUSP_MGR" --emit-audit --gate "$gate" \
        --authorized-by "$authorized_by" 2>/dev/null || true
```

The bash `printf` JSON builder and the apostrophe-escape (lines 52–55) are
deleted. The `audit/`-absent guard now lives in Python (`emit_audit`). Emission
failure is non-fatal (matches current `|| true`), because a suspended gate that
cannot write its audit line must still suspend — but note the audit-trail guard
(HOS#106) is preserved: when `audit/` exists and Python is available, the line is
written.

### 4d. `print_suspended(gate)` — unchanged interface (R5)

Still prints the human notice and reads `Authorized by:` from the suspension file
in bash; only its internal `_emit_suspension_audit` call now reaches Python.
Signature, stdout, and exit behavior unchanged.

---

## 5. Boundaries

- The shell external interface (`source check_suspension.sh`; `is_suspended`,
  `print_suspended`) is frozen — no gate script changes (R5). Verified callers:
  `security_scan.sh`, `portability_check.sh`, `django_check.sh`, `type_check.sh`,
  `lint_check.sh`, `secret_scan.sh`, `collection_integrity.sh`,
  `template_refs_check.sh`.
- The grammar is NOT changed; `_SUSPENDED_RE` is the single source of truth.
- `--census`/`--check`/`--auto-remove` behavior is untouched.
- No new audit fields (parity only). The 3 contract-schema gaps are deferred to
  a follow-up issue.

---

## 6. Testability (R4)

Add to `tests/oversight/test_suspension_manager.py` (same `importlib` load pattern):

- `test_emit_audit_writes_gate_suspended_event`: in a tmp dir with `audit/`,
  call `cmd_emit_audit("lint", "Test Human")`, then read
  `audit/oversight-log.jsonl` and assert the single line parses to exactly
  `{"event":"gate-suspended","gate":"lint","authorized_by":"Test Human","timestamp": <ISO>}`
  and the key order is `event, gate, authorized_by, timestamp`.
- `test_emit_audit_noop_without_audit_dir`: in a tmp dir WITHOUT `audit/`, call
  `cmd_emit_audit(...)` and assert no file is created and no exception is raised.
- `test_emit_audit_escapes_authorized_by`: pass an `authorized_by` containing a
  `"`; assert the line is valid JSON that round-trips the value.

No subprocess, no git repo, tmp-dir-only side effects — satisfies R4.

---

## 7. Affected sign-offs analysis

This is a reactive consolidation of a previously-shipped duplication (HOS#105),
not a late correction to an already-built feature against a changed contract.
The behavioral contract (exit codes, audit JSON field set) is **preserved**, so
prior sign-offs on the gate scripts that *source* this helper stand. The
`check_suspension.sh` internals and the new `suspension_manager.py` entry point
require fresh review (code-review + security lens, since this is a safety-gate
bypass path). No orphaned approvals: no consumer of the frozen shell interface
changes behavior.

This is **not** a `startup-artifact-gap`: the duplication was a known,
documented sync hazard (the line-33 comment), and SPEC-337 is the planned
de-duplication, not a missed initial-design item.

---

## 8. Follow-up (out of scope here)

File `feat(#337-followup): complete gate-suspended audit event schema — add
step, suspension_file, reason_category fields` to track filling the three
contract-schema fields (`OVERSIGHT-CONTRACT.md §6a`) that the parity build
deliberately omits.

---

## HOS self-flag

RISK: MEDIUM — touches a safety-gate bypass control path (gate suspension),
but the change is behavior-preserving by contract (exit codes and audit JSON
held identical) and the fail-safe is fail-closed (gate runs on any Python fault).
CONFIDENCE: HIGH — canonical regex and `emit_audit()` already exist and are
tested; the change removes a duplicate rather than adding logic.

Change classification: **structural** (deletes a parallel parser on a safety path
and re-routes a bash control path through a subprocess). Per CORE, a structural
design change is escalated to a human before the contract is acted on.

## Human Review Required

- This design deletes the bash suspension-regex copy and makes the gate-skip
  decision depend on a `python3` subprocess. The fail-closed binding (gate runs
  on any Python fault) is the safety pivot — confirm exit-1-on-failure is the
  intended posture for every gate that sources this helper.
- Confirm parity-only audit scope (no `step`/`suspension_file`/`reason_category`)
  is acceptable for the interim, with the follow-up issue tracking the gap.
