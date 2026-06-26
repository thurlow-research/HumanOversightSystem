# Technical Design — SPEC-888: Per-Entry Audit Log Directory

**Issue:** #888
**Spec:** `docs/specs/SPEC-888-audit-log-per-entry-directory.md`
**Status:** For implementation (phased; human review gate before Phase 1)
**Milestone:** v0.4.2
**Date:** 2026-06-26
**Author:** technical-design

---

## 1. Overview

This design replaces the single append-only audit file `audit/oversight-log.jsonl` with a
directory of write-once, one-event-per-file records under `audit/log/<YYYY>/<MM>/`. Because
git merges files independently, two branches writing audit events under distinct filenames
can never textually conflict — eliminating the conflict at its source rather than syncing
around it (#861).

Two seams carry the whole design:

- a **writer helper** (`audit_write_event`) that maps an event object to a record path
  (per SPEC §6) and writes the file write-once; and
- a **read-shim** (`audit_read_stream`) that globs + sorts + concatenates the directory into
  the legacy JSONL **event stream**, so existing readers change only their source of input.

Both seams exist in Bash and Python, sharing one canonical byte serialization. All other code
talks to those two seams. The change is mostly mechanical once the seams exist; the risk is in
the canonicalization contract (cross-language byte-identity) and in retiring the #861 workaround
without breaking any consumer.

This document plus SPEC-888 are the **design deliverable** for #888, intended for human review
**before** Phase 1, because the change rewrites the substrate every oversight event flows through.

---

## 2. Components and contracts

### 2.1 `scripts/oversight/lib/audit_log.py` (new — canonical helper)

Single source of truth for serialization, naming, writing, and reading.

```
canonical_bytes(event: dict) -> bytes
    # UTF-8 of json.dumps(event, sort_keys=True, separators=(",",":"), ensure_ascii=False) + b"\n"

record_relpath(event: dict, ts: str) -> str
    # "<YYYY>/<MM>/<ts>-<slug>-<hash12>.json"
    #   ts    : caller-supplied UTC "YYYY-MM-DDTHHMMSSZ" (writer derives it once; see 2.3)
    #   slug  : re.sub(r'[^a-z0-9]+','-', str(event.get("event","event")).lower()).strip('-')
    #   hash12: sha256(canonical_bytes(event)).hexdigest()[:12]
    #   YYYY/MM derived from ts (NOT re-read from a clock — ts is authoritative)

write_event(event: dict, *, root: str = ".", ts: str | None = None) -> str
    # ts defaults to now() in UTC formatted per grammar, ONLY here (single clock read).
    # Computes <root>/audit/log/<relpath>, mkdir -p the shard dir, write canonical_bytes
    # write-once: if the path exists, assert bytes match and return (idempotent no-op).
    # Returns the relative record path written.

read_stream(root: str = ".") -> Iterator[bytes]
    # find <root>/audit/log -type f -name '*.json', sort by path, yield each file's bytes.
    # Absent/empty dir -> yields nothing, no error.
```

**Contracts:**

- `canonical_bytes` is the ONLY place serialization is defined. `<hash>` is computed over its
  output, and the same output is what lands on disk — so the filename hash always matches the
  file content (self-consistency, idempotency).
- `write_event` reads the wall clock at most once, to derive `ts`. Everything downstream
  (shard dirs, filename) is derived from that `ts`, so a record is internally consistent even
  across a second boundary.
- Write-once: re-writing an existing path asserts byte-equality and is otherwise a no-op. A
  byte mismatch at an existing path is a hard error (indicates a hash collision on
  non-identical content — not expected for SHA-256/12-hex at our volumes; fail loud).
- `read_stream` is total: missing directory → empty stream, exit 0. This preserves the
  contract `step_range.sh` relies on today (missing log → empty output, not an error).

### 2.2 `scripts/oversight/lib/audit_log.sh` (new — Bash facade)

A sourced library (no side effects at source time, no `set -e` leakage), exporting two
functions that delegate canonicalization to the Python module so there is exactly one
serializer:

```
audit_write_event '<json-event>' [root]
    # echo "$json" | python3 -m scripts.oversight.lib.audit_log write [root]
    # The Python entry point reads the event JSON on stdin, calls write_event, prints the
    # record path. Bash returns that path.

audit_read_stream [root]
    # python3 -m scripts.oversight.lib.audit_log read [root]   # prints the ordered JSONL stream
```

**Why delegate rather than reimplement in pure Bash + `jq`:** the load-bearing requirement is
cross-language byte-identity of the canonical serialization (SPEC R2/T5). Two independent
serializers (Python `json.dumps` vs `jq -cS`) can diverge on number formatting, unicode
escaping, and key collation. Delegating to one Python serializer makes parity true by
construction. `python3` is already a hard dependency of the framework (every reader/writer
listed uses it or its tests do), so this adds no new dependency. The module therefore grows a
tiny `__main__` CLI (`write` reads stdin → writes record → prints path; `read` prints the
stream).

> If a future constraint forbids invoking Python from a Bash writer on a hot path, the
> fallback is a pure-Bash writer using `jq -cS` plus a normalization shim, gated behind T5
> (writer parity) which would then become a real cross-implementation test rather than a
> trivial pass. Not chosen now.

### 2.3 Timestamp derivation

`ts` is UTC `date -u +%Y-%m-%dT%H%M%SZ` (Bash) / `datetime.now(timezone.utc).strftime(...)`
(Python). Colon-free per SPEC §6 (NTFS validity, glob safety). It is read once per event by
the writer and threaded into both the shard path and the filename, never re-derived.

### 2.4 Record layout (recap of SPEC §6)

```
audit/log/2026/06/2026-06-26T143000Z-gate-suspended-9f3a1c0b7d22.json
          └YYYY┘└MM┘ └────── ts ──────┘ └── slug ──┘ └─ hash12 ─┘
```
Full-path lexical sort == chronological because `YYYY`, `MM`, and `ts` are all fixed-width,
zero-padded, and mutually consistent (all derived from the same instant).

---

## 3. Writer migration (SPEC R5)

Each writer stops appending to `oversight-log.jsonl` and instead calls the helper. The event
object each constructs today is reused unchanged; only the sink changes.

| Writer | Today | After |
|---|---|---|
| `scripts/oversight/run_with_retry.sh` | `echo "$json" >> audit/oversight-log.jsonl` (line ~113) | `source lib/audit_log.sh; audit_write_event "$json"` |
| `scripts/oversight/suspension_manager.py` | append to `AUDIT_LOG` (line ~412) | `from .lib.audit_log import write_event; write_event(event, root=repo_root)` |
| `scripts/oversight/release_artifact_logic.py` | `_append_event(...)` to `--log-to` path (line ~215) | call `write_event`; keep `--log-to` flag accepting a *root* (back-compat shim, see §6) |
| `scripts/automation/lib/cycle_log.py` | append to resolved `oversight-log.jsonl` (line ~28) | `write_event` against the resolved repo root |
| `scripts/run_redteam_sample.sh` | `AUDIT_LOG="audit/oversight-log.jsonl"` (line ~220) | `audit_write_event` |

The implementer MUST `grep -rn "oversight-log.jsonl" scripts/` after migration and confirm only
comments / doc-strings remain (no live appenders). `signoff_gate.py` and
`stale_commit_detector.py` reference the path only in comments — verify, do not change behavior.

---

## 4. Reader migration (SPEC R4)

Each reader replaces "read the JSONL file" with "read the shim stream". The downstream parsing
logic is untouched.

| Reader | Change |
|---|---|
| `scripts/oversight/lib/step_range.sh` | `_shr_preferred_head` consumes `audit_read_stream` instead of `cat "$log"`. The optional `log_path` arg becomes an optional `root` arg; default resolves to repo root. Missing-dir → empty stream preserves the current "no event → empty output, exit 0" contract. |
| `scripts/oversight/audit_conditional_proceed.sh` | `LOG_PATH` resolution replaced by `audit_read_stream "$REPO_ROOT"`; `--log` override becomes `--root` override. |
| `scripts/automation/lib/cycle_log.py` | dual role (reader+writer); reads via `read_stream`. |

**Backward-compat for tests:** `step_range.sh`'s `get_step_range <step_n> [log_path]` second
arg is used by fixtures. It is repurposed to `[root]`; the reader tests (§5) are updated to lay
down a fixture `audit/log/` tree under a temp root instead of a single fixture file.

---

## 5. Tests (SPEC §8)

| ID | Test | Location |
|---|---|---|
| T1 | Read-shim equivalence vs snapshot of legacy stream | new `tests/oversight/test_audit_log.py` |
| T2 | Reader behavior unchanged | adapt `test_step_range.py`, `test_suspension_manager.py`, `test_cycle_log.py` to fixture `audit/log/` |
| T3 | Conflict-free merge property (two branches, two records, merge, assert 0 conflicts + both present) | `tests/oversight/test_audit_log.py` (uses a temp git repo) |
| T4 | Cross-month-shard ordering via plain path sort | `test_audit_log.py` |
| T5 | Bash/Python writer parity — byte-identical path + content | `test_audit_log.py` (invokes both helpers) |
| T6 | Migration round-trip: no loss, idempotent, clean read-shim diff | `tests/framework/test_migrate_audit_log.py` (or bash test) |

All run under `scripts/framework/run_tests_inner_loop.sh`; validators via
`scripts/oversight/run_validators.sh`.

---

## 6. Workaround retirement (SPEC R6)

Sequenced last, after writers+readers prove out:

1. `git rm --cached audit/oversight-log.jsonl`.
2. Delete `.gitignore` line 44 (`audit/oversight-log.jsonl`). Keep line 45
   (`audit/overnight-loop-log.md`) — different artifact, out of scope.
3. `git rm .github/workflows/sync-audit-log.yml`.
4. Grep CI, scripts, and docs for the `audit-log` branch and `audit/overseer-cycle-*`; remove
   dead references. The remote branches themselves are deleted by a human operator (worker does
   not delete remote branches autonomously).
5. `release_artifact_logic.py --log-to` and `cut_release.sh` references: the `--log-to
   audit/oversight-log.jsonl` invocation becomes `--root .` (or the flag is dropped if the
   default root suffices). Keep `cut_release.sh` and `release_artifact_logic.py` in lockstep in
   the same PR — they are a coherent unit.

`pre_pr_stale_check.py` lists `audit/oversight-log.jsonl` among audit-only files (lines ~52/70);
update its allowlist to treat `audit/log/**` as audit-only so the stale-commit gate keeps
classifying audit records correctly. This is load-bearing — missing it would make every audit
record look like a non-audit change to the pre-PR gate.

---

## 7. One-time migration script (SPEC R7)

`scripts/migrate_audit_log_to_dir.sh` (disposable; header comment marks it throwaway):

```
usage: migrate_audit_log_to_dir.sh --log <path/to/oversight-log.jsonl> [--root <repo-root>]
```

- Reads the source log line by line; for each line, parse JSON and call the **same**
  `write_event` (via `python3 -m scripts.oversight.lib.audit_log write`) so migrated records are
  byte-identical to freshly-written ones and idempotent on re-run.
- Timestamp source: each legacy event carries its own timestamp field (e.g. `ts`/`timestamp`);
  the script extracts it and passes it as the explicit `ts` so historical records keep their
  real time rather than migration time. (The migration MUST NOT stamp `now()`.) If a legacy
  line lacks a parseable timestamp, the script fails loud and names the line — no silent
  fabrication.
- Round-trip check: after migration, `audit_read_stream` over the output, diff against a
  normalized form of the source (both passed through `canonical_bytes`), assert empty diff and
  equal line counts; print `OK: <n> records migrated, round-trip clean`.
- Does NOT delete the source log (R6 owns deletion post-verification).
- Portable: no hard-coded HOS path; `--log`/`--root` args drive it; runs against a CPS checkout
  by pointing `--root` at the CPS repo. Deleted after HOS+CPS upgrades (close-out follow-up).

---

## 8. Phased rollout (resolves SPEC OQ-4; respects ≤15-file / ≤10-commit PR budget)

Each phase is one worker PR. The read-shim makes migrated history and new records coexist, so
there is no dual-write window.

| Phase | Deliverable | Approx. files |
|---|---|---|
| **P0 (this PR)** | SPEC-888 + this technical design. Design gate for human review. | 2 |
| **P1** | `audit_log.py` + `audit_log.sh` helpers, module `__main__` CLI, `test_audit_log.py` (T1,T3,T4,T5). No caller migrated yet. | ~3 |
| **P2** | Migrate writers (R5) to `audit_write_event`/`write_event`; adapt writer tests (T2 writer side). | ~8 |
| **P3** | Migrate readers (R4); adapt reader tests (T2 reader side). | ~6 |
| **P4** | Migration script + round-trip test (R7, T6); run it to land migrated history under `audit/log/`. | ~3 |
| **P5** | Retire workaround (R6): un-track legacy file, drop `.gitignore` entry, delete sync workflow, fix `pre_pr_stale_check` allowlist, scrub `audit-log` branch references, update docs (README/CLAUDE/runbook) describing the new layout. | ~10 |

Ordering rationale: helpers before callers (P1); writers before readers (P2→P3) so by the time
readers switch, real records already exist; migration (P4) before retirement (P5) so history is
present in the new layout before the old file is untracked. P5 is last because it is the only
irreversible-feeling step and should run once everything green.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Cross-language serialization drift breaks the filename hash contract | One serializer (Python) behind both facades; T5 asserts byte-identity; Bash delegates rather than reimplements. |
| A missed writer keeps appending to the dead file → silent split-brain | Post-P2 grep gate (§3) asserts no live appender to `oversight-log.jsonl` remains; CI grep check optional. |
| `pre_pr_stale_check` mis-classifies audit records as code → blocks PRs | P5 updates its audit-only allowlist to include `audit/log/**` (§6); covered by `test_pre_pr_stale_check.py`. |
| Reader contract regressions (e.g. `step_range` empty-log behavior) | `read_stream` is total (missing dir → empty stream); T2 reuses existing reader tests; T1 snapshot diff. |
| Historical timestamps lost during migration | R7 threads each legacy event's own timestamp as explicit `ts`; fails loud on unparseable lines (§7). |
| Per-file records weaker tamper-evidence than a chained file | Accepted (SPEC OQ-1): git history is the integrity layer; chaining would re-couple branches. Optional future signed manifest noted below. |

---

## 10. Future work (out of scope)

- **Signed periodic manifest.** A per-release manifest listing record hashes, signed, would
  restore deletion-detection without re-coupling concurrent writers. Additive; deferred.
- **Compaction/archival.** Thousands of tiny files per year are fine for git, but a yearly
  `audit/log/<YYYY>/` tarball-on-release policy could be considered if listing latency grows.
- **Delete the migration script** once HOS and CPS both complete the upgrade (close-out
  follow-up issue).
