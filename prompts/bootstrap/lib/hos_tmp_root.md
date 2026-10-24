# Prompt Artifact — hos_tmp_root.py

| Field | Value |
|---|---|
| **Generated file** | `bootstrap/lib/hos_tmp_root.py` |
| **Description** | #2148 register() full write + temp unlink on failure |
| **Date** | 2026-10-24 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Worker → coder subagent dispatch (single turn), summarized faithfully from the dispatch text:

```
Implement GitHub issue #2148 (a bug fix, no separate design doc) on branch
worker-2148-register-short-write-261024170501-17816.

The bug: register() in bootstrap/lib/hos_tmp_root.py writes the new registry JSON to
"{path}.new.{pid}" then os.rename()s it over the registry. (1) os.write(fd, payload)
ignores its return value — a short write then fsync+rename puts a truncated JSON file
over the registry. (2) If os.write/os.fsync/os.rename raises (e.g. ENOSPC), the
.new.<pid> file is never unlinked.

Required: loop on os.write until all bytes are written; a 0-byte write with bytes
remaining is an error (no infinite loop); never rename a partial file. On ANY failure
after the temp file is created, unlink it best-effort, then raise TmpRootError naming
the registry path and the cause (OSError text; say so explicitly for zero progress),
chained with `from exc`. Close the fd exactly once; keep the lock_fd flock/finally
intact; preserve success behaviour (atomic temp + rename, O_EXCL). Minimal change in
module style (a small private helper such as _write_all is fine).

Tests in tests/framework/test_hos_tmp_root.py: register one role normally, capture the
registry bytes, then attempt a second registration with a fault injected and assert
TmpRootError (message names the cause), registry byte-identical, no *.new.* left.
Cases: short write; os.write raising ENOSPC; os.fsync raising; os.rename raising; plus
a success case where os.write writes in small chunks. Patch only the registry write
(not the marker-file os.write).

Run the module tests; commit only the two changed files with LOW trailers.
```

## Constraints Specified

- Python stdlib only (`os`, no new dependencies).
- Must NOT rename a partially written file over the registry.
- Must NOT leave `tmp-roots.json.new.<pid>` behind on any failure path.
- Must NOT change the flock structure or success-path semantics.
- Must NOT commit unrelated working-tree files.

## Refinement History

First attempt worked. Risk tier raised LOW → MEDIUM by the validators after coding
(composite 0.4544), so this artifact and the MEDIUM trailers were added by the worker
before the risk-assessor ran.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `bootstrap/lib/hos_tmp_root.py`
4. Note any drift in a new version artifact (`hos_tmp_root.v1.md`)
