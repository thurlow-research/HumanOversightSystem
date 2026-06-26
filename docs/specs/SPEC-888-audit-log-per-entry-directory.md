# Requirements Spec — Issue #888: Per-Entry Audit Log Directory

**Document type:** Requirements specification
**Status:** Draft — for technical-design (companion: `TECHNICAL-DESIGN-888-audit-log-per-entry-directory.md`)
**Issue:** #888
**Milestone:** v0.4.2
**Supersedes:** #861 (sync-bot mitigation)
**Related (shared root cause):** #873, #849, #842, #832, #821, #820, #813, #809
**Date:** 2026-06-26
**Author:** pm-agent

---

## 1. Problem Statement

The oversight audit trail is a single append-only file, `audit/oversight-log.jsonl`.
Every branch that emits an audit event appends a line to the **tail of the same file**.
Two branches that each log an event therefore produce overlapping edits to the same
region of the same file, and merging them to `main` produces a textual conflict. With
autonomous worker and overseer cycles each emitting audit events on their own branches,
this conflict is the steady-state, not the exception.

The prior mitigation (#861) — gitignore the file and sync it to `main` from a dedicated
`audit-log` branch via `.github/workflows/sync-audit-log.yml` — **never took effect**,
because `audit/oversight-log.jsonl` was committed *before* the ignore rule was added and
is therefore still tracked. `.gitignore` has no effect on a tracked file, so every branch
keeps committing to the shared file and merges keep conflicting. The sync bot treated a
symptom; the disease — N branches editing one shared append-only file — was never
addressed. This is the shared root cause behind the `process-gap` cluster cited above.

## 2. Goal

Replace the single append-only file with a directory of immutable, one-event-per-file
records (the changesets / towncrier / maildir pattern: git merges per-file, so distinct
filenames never conflict). The resulting audit trail must:

1. **Never merge-conflict, structurally** — two branches writing audit events must never
   touch the same file.
2. Be **committed inline with the PR that produced it** — no gitignore, no async sync bot;
   the audit records appear in the PR diff and are reviewable there.
3. Preserve chronological ordering and all existing event semantics for current readers.

## 3. Scope

In scope:

- A new audit record layout under `audit/log/` (per-event files, month-sharded).
- A filename grammar that is lexically-chronological and collision-proof across branches.
- A shared **writer** helper, available to both Bash and Python writers.
- A shared **read-shim** that reconstructs the legacy JSONL event stream from the directory,
  available to both Bash and Python readers.
- Migration of all known writers and readers to the new layout.
- Retirement of the #861 workaround (gitignore entry, sync workflow, `audit-log` /
  `audit/overseer-cycle-*` branch machinery).
- A disposable, portable one-time migration script (HOS **and** CPS).
- Regression tests asserting reader output is identical to the legacy layout.

Out of scope (see §10):

- Any change to *what* events are emitted or to event field semantics.
- Tamper-evidence via hash-chaining (decision recorded in §9; accepted trade-off).
- Changing the on-disk format of `audit/overnight-loop-log.md` (a different artifact).

## 4. Definitions

| Term | Meaning |
|---|---|
| **Record** | One audit event serialized as a single JSON object, written to its own file under `audit/log/`. Write-once, never modified. |
| **Event stream** | The legacy view: all records concatenated in chronological order, one JSON object per line — byte-for-byte the shape readers consume today from `oversight-log.jsonl`. |
| **Read-shim** | A helper that globs `audit/log/`, sorts by path, and emits the event stream. The single seam every reader uses. |
| **Writer helper** | A helper that, given an event object, computes the record path per §6 and writes the file. The single seam every writer uses. |
| **Legacy log** | The existing single file `audit/oversight-log.jsonl`. |

## 5. Functional Requirements

### R1 — One file per event (write-once)
Each audit event is written as its own file under `audit/log/`. A record is never modified
or appended-to after creation. Re-emitting a byte-identical event resolves to the same path
(§6) and is therefore an idempotent no-op.

### R2 — Unique, sortable, collision-proof filenames (load-bearing)
The record filename MUST satisfy all of:

- **Lexical = chronological.** The leading component is a fixed-width, zero-padded UTC
  timestamp such that a plain lexical sort of filenames is a correct chronological sort.
- **Collision-proof across branches.** Two events MUST NOT collide on filename unless they
  are byte-identical (in which case collision is the desired idempotent no-op, R1). A bare
  second-granularity timestamp is **not** sufficient — retry loops, release bursts, and two
  overseer cycles on two branches all produce same-second events. The filename therefore
  carries a content-derived disambiguator (a short content hash; see §6).
- **Reproducible from Bash and Python.** Both writer implementations MUST produce the same
  filename for the same record bytes (§6 fixes the canonical byte representation and hash).
- **Filesystem-portable.** The filename MUST be valid on ext4, APFS, and NTFS, and safe in
  shell globs (no `:`; no characters requiring quoting). See §6 for the chosen grammar.

### R2a — Chronological viewing without parsing
A human or tool MUST be able to read the full audit trail in true chronological order using
only a plain lexical sort of paths — `find audit/log -type f | sort`, `ls -R audit/log`, or a
directory glob — with no need to open or parse file contents. The month-shard prefix (R3) and
the R2 filename grammar MUST compose so that full-path lexical order equals event order
**across shard boundaries**. The read-shim (R4) is the supported convenience that prints the
ordered stream.

### R3 — Month sharding
Records are permanent and will number in the thousands. They MUST be sharded by UTC month:
`audit/log/<YYYY>/<MM>/<filename>`. The shard segments are themselves zero-padded and
chronological, so a full-path lexical sort remains a correct chronological sort across
shard boundaries.

### R4 — Read-shim; readers unchanged in spirit
A single read-shim MUST reconstruct the legacy event stream (chronologically-ordered JSONL on
stdout) from `audit/log/`. All current readers MUST consume the stream through this shim, so
their existing logic (e.g. "latest event for step N") is unchanged except for the source of
the stream. Known readers to migrate:

- `scripts/oversight/lib/step_range.sh` (latest event for a step → HEAD/base SHA)
- `scripts/oversight/audit_conditional_proceed.sh`
- `scripts/automation/lib/cycle_log.py`

The shim MUST be available to both Bash and Python readers (§7 fixes where it lives). The
shim MUST tolerate an absent/empty `audit/log/` directory by emitting an empty stream and
exiting 0 (the same contract `step_range.sh` relies on today for a missing log file).

### R5 — All writers migrated
All known writers MUST emit per-file records via the writer helper. Known writers:

- `scripts/oversight/suspension_manager.py`
- `scripts/oversight/run_with_retry.sh`
- `scripts/oversight/release_artifact_logic.py`
- `scripts/automation/lib/cycle_log.py`

The implementer MUST grep for any additional direct appenders to `oversight-log.jsonl`
(e.g. `scripts/run_redteam_sample.sh`, `scripts/oversight/release_artifact_logic.py`
`--log-to`) and migrate or explicitly account for each.

### R6 — Retire the workaround
Once writers and readers are migrated and verified:

- `git rm --cached audit/oversight-log.jsonl` (stop tracking the legacy file).
- Remove its `.gitignore` entry (line 44) — the new layout is committed inline, not ignored.
- Delete `.github/workflows/sync-audit-log.yml`.
- Retire the `audit-log` and `audit/overseer-cycle-*` branch machinery and confirm nothing
  else depends on them (grep CI, docs, and scripts for `audit-log` branch references).

The implementer MUST confirm no remaining reference to the sync workflow, the `audit-log`
branch, or the ignore entry survives in CI, scripts, or docs.

### R7 — One-time migration script (disposable)
A standalone shell script MUST convert an existing `oversight-log.jsonl` into the new
per-file, month-sharded layout. It MUST be:

- **Portable across repos.** Runs against both HOS and CPS. Takes the log path / repo root as
  an argument; hard-codes no HOS-specific path.
- **Idempotent & safe.** Re-running MUST NOT duplicate or corrupt records (filename is
  content-derived, so re-emitting the same line is a no-op). It MUST NOT delete the source
  log — R6 owns deletion once the result is verified.
- **Deterministic & verifiable.** No data loss: every source line maps to exactly one output
  file. It MUST provide a round-trip check (concatenate output via the read-shim, diff against
  the source stream).
- **Explicitly throwaway.** A header comment MUST mark it as a transition tool, not part of
  the installer or framework surface. It is deleted after HOS and CPS both complete the
  upgrade (tracked as a close-out follow-up).

## 6. Filename Grammar (resolves OQ: grammar + hash)

```
audit/log/<YYYY>/<MM>/<ts>-<event>-<hash>.json
```

| Component | Definition | Example |
|---|---|---|
| `<YYYY>` | 4-digit UTC year (R3 shard) | `2026` |
| `<MM>`   | 2-digit zero-padded UTC month (R3 shard) | `06` |
| `<ts>`   | UTC timestamp, extended date + basic time, no colons: `YYYY-MM-DDTHHMMSSZ`. Fixed-width, zero-padded, lexically chronological, colon-free for filesystem portability (R2). | `2026-06-26T143000Z` |
| `<event>`| Event-type slug: the record's `event` field, lowercased, non-`[a-z0-9]` runs collapsed to `-`. Human legibility only; not load-bearing for ordering or uniqueness. | `gate-suspended` |
| `<hash>` | First 12 hex characters of the SHA-256 of the **record's exact file bytes** (the canonical JSON serialization defined below). Collision-proof disambiguator (R2). | `9f3a1c0b7d22` |

Full example: `audit/log/2026/06/2026-06-26T143000Z-gate-suspended-9f3a1c0b7d22.json`

**Deviation from the issue's illustrative example:** the issue shows
`2026-06-26T14:30:00Z-…`. This spec drops the colons (`14:30:00` → `143000`) for NTFS
validity and shell-glob safety. Both forms are fixed-width and sort identically; the
colon-free form is the normative grammar.

**Canonical serialization (load-bearing for cross-writer reproducibility).** The bytes
written to the file — and the bytes hashed for `<hash>` — MUST be the UTF-8 encoding of
`json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` followed by a
single trailing `\n`. Both the Bash and Python writer helpers MUST produce these exact bytes,
and MUST hash exactly those bytes. (The Bash helper achieves this by delegating canonical
serialization to a small Python one-liner or `jq -cS`; the technical design fixes the
mechanism and a contract test asserts byte-identical output between the two helpers.)

**Collision semantics.** Two records collide on `<hash>` (and `<ts>`) only when their
canonical bytes are identical, i.e. they are the same event at the same UTC second. Treating
that as an idempotent no-op (R1) is correct: such records are indistinguishable. Distinct
same-second events differ in at least one field and therefore in their hash.

## 7. Component Placement (resolves OQ: shim language + location)

The read-shim and writer helper are needed from **both** Bash and Python callers, so each is
provided in both languages, kept in lockstep by a contract test (§8):

| Component | Bash | Python |
|---|---|---|
| Writer helper | `scripts/oversight/lib/audit_log.sh` → `audit_write_event` | `scripts/oversight/lib/audit_log.py` → `write_event(...)` |
| Read-shim | `scripts/oversight/lib/audit_log.sh` → `audit_read_stream` | `scripts/oversight/lib/audit_log.py` → `read_stream(...)` |

The two implementations share the §6 grammar and canonical serialization. The technical
design specifies whether the Bash helper shells out to the Python module for serialization
(preferred — single source of truth for canonicalization) or reimplements it via `jq`.

## 8. Testing Requirements

- **T1 — Read-shim equivalence (regression).** Snapshot the current event-stream output of
  the legacy log. Migrate it via R7, run the read-shim over the result, and assert the stream
  is byte-identical to the snapshot. This is the load-bearing no-regression check for R4.
- **T2 — Reader behavior unchanged.** Existing reader tests (`tests/oversight/test_step_range.py`,
  `tests/oversight/test_suspension_manager.py`, `tests/automation/test_cycle_log.py`) MUST pass
  against the new layout, adapted only to point at `audit/log/` via the shim.
- **T3 — Conflict-free property.** A test simulates two branches each writing a distinct audit
  event, merges both into a common tree, and asserts zero conflicts and both records present.
- **T4 — Ordering across shard boundaries.** Records spanning a month boundary sort
  chronologically by plain path sort (R2a/R3).
- **T5 — Writer parity.** The Bash and Python writer helpers produce a byte-identical file
  (same path, same content) for the same event object.
- **T6 — Migration round-trip.** R7 script on a fixture log: every source line maps to exactly
  one output file; read-shim of the output diffs clean against the source stream; a second run
  is a no-op (idempotency).

All changes go through the inner-loop test runner and the oversight validators
(`scripts/framework/run_tests_inner_loop.sh`, `scripts/oversight/run_validators.sh`).

## 9. Acceptance Criteria

- Two branches that each append an audit event both merge to `main` with **zero conflicts**
  in the audit trail, and both records are present (T3).
- `find audit/log -type f | sort` yields entries in true chronological order across
  month-shard boundaries, verifiable without parsing contents (R2a/T4).
- All existing readers produce results identical to the legacy layout (T1/T2).
- The R7 migration script converts the current `oversight-log.jsonl` with zero data loss
  (round-trip diff), is idempotent on re-run, and runs unmodified against a CPS checkout given
  its log path (T6).
- No audit data is lost in migration; historical entries are present in the new layout.
- `sync-audit-log.yml`, the `.gitignore` entry, and the `audit-log` branch dependency are
  gone, with no remaining references (R6).
- The migration script is deleted after HOS + CPS upgrades complete (tracked as a follow-up
  close-out, not in the migration PR itself).

## 10. Resolved Open Questions

The issue left four questions for the SPEC. They are resolved here:

### OQ-1 — Tamper-evidence: chain, manifest, or accept the trade-off?
**Decision: accept the trade-off; do NOT add per-record hash-chaining now.** Rationale:

1. **Not a regression.** The current single-file log is not hash-chained either, so moving to
   per-file records does not weaken any attestation that exists today.
2. **Chaining defeats the primary goal.** A `prev`-hash chain reintroduces a shared-tail
   dependency: each new record references the prior record's hash, so two branches appending
   concurrently would both claim the same predecessor and produce divergent chains that must
   be reconciled on merge — exactly the coupling this issue exists to remove.
3. **Git already provides tamper-evidence.** Every record is added as a committed, signed-off
   diff with `Supervised-by` attribution; deleting or altering a committed record is visible
   in `git log -- audit/log/...` and in branch protection history. The version-control layer is
   the integrity layer.

**Documented residual risk:** a directory of independent files makes deletion of a single
record less self-evident than truncating a chained file would be. This is accepted. A
**future, optional** enhancement is a periodic (e.g. per-release) signed manifest that lists
record hashes — additive, out of scope here, and recorded in the technical design's "future
work."

### OQ-2 — Filename grammar and hash algorithm.
Resolved in §6: `<ts>-<event>-<hash>.json`, colon-free UTC `YYYY-MM-DDTHHMMSSZ` timestamp,
12-hex SHA-256 of the canonical record bytes, month-sharded under `audit/log/<YYYY>/<MM>/`.

### OQ-3 — Read-shim language and location.
Resolved in §7: provided in both Bash and Python under `scripts/oversight/lib/audit_log.*`,
kept in lockstep by a contract test (T5), with canonical serialization as the single source of
truth shared between them.

### OQ-4 — Migration sequencing: big-bang vs dual-write transition.
**Decision: no dual-write window; phased single-direction cutover, sequenced to respect the
PR size budget.** The read-shim lets historical (migrated) and new records coexist in one
layout, so a dual-write period (writing both old file and new dir) is unnecessary and would
keep the conflict-prone file alive. The technical design specifies the phase breakdown
(libraries + tests → writers → readers + workaround retirement + migration) so no single PR
exceeds the worker's ≤15-file / ≤10-commit budget. This SPEC + technical design is the first
deliverable; implementation follows in the phased PRs.

## 11. Implementation Note — Phasing (informative)

Because the full migration touches writers, readers, CI, tests, and docs across well more than
15 files, it cannot ship as a single worker PR. The companion technical design defines a
phased rollout; this document and that design are the **design deliverable** for #888 and are
intended for human review **before** the invasive implementation begins, consistent with the
framework's own posture toward high-surface changes to the oversight substrate.
