# SPEC-267: Structural-Override Auth File Enumeration

**Status:** Draft — for architect review
**Issue:** #267
**Author:** pm-agent
**Date:** 2026-06-17

---

## 1. Problem Statement

The structural-override check (contract §2a, condition 10) is the anti-gaming gate that
prevents an authoring agent from self-classifying an `additive` or `clarifying` change
when the diff contains a mechanical structural signature (new dependency, new auth check,
new route, new user-facing surface, new user-facing state). When the signature is present
and no covering human-authorization artifact exists, the evaluator fires a COMPLIANCE FAIL.

When a human authorization artifact does exist — `.claudetmp/oversight/step{N}-human-authorization.md`
— the evaluator skips condition 10 entirely. This is the correct behavior in principle: a human
cleared the gate, so re-derivation need not run. But the gate-clearing logic currently rests on
a freeform file whose content is not verified against the actual diff surface.

The governance hole: the skip logic checks only that the authorization file is non-empty. It
does not verify that the authorization file claims to cover the files actually present in the
diff. A human who authorized a change to file A, and who is re-presented with a fabricated
auth file referencing only file A, cannot detect that the diff also includes file B (which
carries its own structural-override signature). Similarly, an auth file could be recycled from
a prior step or partially copied with no connection to the current diff. The evaluator accepts
any non-empty file as sufficient — the skip is justified by existence, not by coverage.

This is the same anti-gaming shape that conditions 9 and 10 were designed to close: a
self-reported value that loosens oversight must be independently verified against the diff.
The authorization file asserts coverage; that assertion must be checkable.

---

## 2. Scope

This spec covers:

1. **Auth file schema** (`.claudetmp/oversight/step{N}-human-authorization.md`): the file gains
   a required `reviewed_files:` field that enumerates the diff surface the human claims to have
   reviewed. The orchestrator's ESCALATE prompt (which instructs the human to create this file)
   is updated to include the field.

2. **Re-derivation skip logic** (contract §7, condition 10): the condition-10 skip is valid only
   when the auth file enumerates at least one file that was present in the diff. An auth file
   without the `reviewed_files:` field, or with an empty or entirely non-overlapping file list,
   does not satisfy the gate — condition 10 runs regardless.

3. **Oversight-orchestrator ESCALATE prompt** (`.claude/agents/oversight-orchestrator.md`):
   the file-creation instruction shown to the human when a CRITICAL step requires authorization
   must include the `reviewed_files:` field in the example so humans produce compliant files.

4. **Oversight contract** (`contract/OVERSIGHT-CONTRACT.md`): the human-authorization file format
   in §1 and the condition-10 check in §7 are updated to document the `reviewed_files:`
   requirement and the enumeration-based skip logic.

This spec does NOT cover:

- The re-derivation logic itself (what patterns condition 10 checks, which structural signatures
  it detects). Those are defined in contract §2a and `change_classifier.py`. This spec changes
  only when condition 10 may be skipped — not what it checks when it runs.
- The `human-tier-override.md` file, which follows a separate code path. Tier overrides are
  not affected by this spec.
- The `step{N}-spec-structural-auth.md` file used by condition 14 (doc-modification coverage).
  That file path and schema are defined in `SPEC-evaluator-re-derivation.md` §4. Its skip logic
  follows the same pattern but is not within this spec's scope.
- Changes to how the human opens the authorization file. The human still creates the file; this
  spec only constrains what the file must contain to satisfy the gate.

---

## 3. Requirements

### R1 — Auth file gains a `reviewed_files:` enumeration field

The human-authorization file for a build step — `.claudetmp/oversight/step{N}-human-authorization.md`
— must contain a `reviewed_files:` field that lists the file paths the human claims to have
reviewed as part of this authorization decision.

Required file format (additions to the existing two-field format in bold):

```
Authorized: {ISO-8601 date}
Decision: {explicit decision text}
Authorized by: {name}
reviewed_files:
  - {path/to/file.py}
  - {path/to/other_file.html}
```

The `reviewed_files:` field value is a YAML-style list (one `  - {path}` entry per line). Paths
are relative to the project root, matching the paths as they appear in `git diff --name-only`.
The list must contain at least one entry. An empty list (`reviewed_files:` with no items) is
treated the same as absent.

The existing required fields (`Authorized:`, `Decision:`, `Authorized by:`) are unchanged.
`reviewed_files:` is added as a fourth required field for authorization files created after this
spec is implemented. Authorization files created before this spec ships are grandfathered; the
evaluator emits a COMPLIANCE WARN (not FAIL) for a present-but-non-compliant file lacking the
field, to avoid breaking existing CRITICAL step histories.

### R2 — Skip is valid only when `reviewed_files:` overlaps the diff

The oversight evaluator's condition-10 skip logic must verify that the authorization file's
`reviewed_files:` enumeration overlaps with the files present in the current step's diff before
accepting the skip.

Specifically, the evaluator must:

1. Parse the `reviewed_files:` list from the authorization file.
2. Obtain the diff file set for this step: `git diff --name-only {base_sha}..{head_sha}` using
   the register header's commit range.
3. Compute the intersection of the two sets.
4. If the intersection is non-empty (at least one listed file appears in the diff) → the skip
   is valid; condition 10 does not run.
5. If the intersection is empty (the auth file lists files not in the diff, or lists no files)
   → the skip is invalid; condition 10 runs as if no authorization file existed.

The intersection check uses exact path matching (case-sensitive, relative to the project root).
Partial-path matches (e.g., a directory prefix matching a file path) are not accepted; the
listed path must exactly match a path in the diff.

### R3 — Absent or empty enumeration invalidates the skip

If the authorization file is present but:
- the `reviewed_files:` field is absent, or
- the field is present but contains no entries (empty list), or
- all listed entries resolve to paths that are not in the diff,

then the authorization file is treated as not covering the structural-override surface for
this step. The evaluator must run condition 10 as if no authorization file existed. This is
not a new compliance condition — it is a tightening of the existing condition-10 skip logic.

The evaluator must report which files in the diff triggered the structural-override signal and
which files (if any) were enumerated in the authorization file but did not match. This output
lets the human understand the coverage gap when fixing the authorization file.

### R4 — Orchestrator ESCALATE prompt includes `reviewed_files:` field

When the oversight-orchestrator prints the CRITICAL STEP AUTHORIZATION REQUIRED block
(instructing the human to create the authorization file), the example contents in that block
must include the `reviewed_files:` field.

Updated example in the orchestrator prompt:

```
Authorized: {date}
Decision: Proceed to panel. Auth system reviewed by hand; rate-limiting fix verified.
Authorized by: {name}
reviewed_files:
  - src/auth/middleware.py
  - src/auth/models.py
```

The instruction text must note that `reviewed_files:` must list the files the human actually
read from the diff — not all files in the repository, not an exhaustive list of unrelated files.

---

## 4. Non-Requirements

- **Does not change what re-derivation checks.** When condition 10 runs (because no valid
  authorization exists), it executes exactly as defined in contract §2a and `change_classifier.py`.
  The structural-override signature set, the loosening-only direction, and the COMPLIANCE FAIL
  behavior are all unchanged. This spec only governs whether condition 10 is permitted to skip.

- **Does not require exhaustive enumeration.** The human is not required to list every file
  in the diff — only the files they reviewed that bear the structural-override signal. A single
  overlapping file is sufficient for the skip check (R2). The enumeration exists to anchor the
  human's claimed review to the diff, not to enforce complete coverage of every changed file.

- **Does not impose a format validator on the Decision field.** The freeform decision text in
  `Decision:` is unchanged. The only new machine-parsed field is `reviewed_files:`.

- **Does not affect the PROCEED or CONDITIONAL_PROCEED paths.** Steps that do not trigger
  condition 10 are unaffected. The enumeration requirement applies only when an authorization
  file is being used to skip condition 10.

- **Does not retroactively invalidate prior authorizations.** Steps completed before this spec
  ships may have authorization files without `reviewed_files:`. Those files are grandfathered
  (COMPLIANCE WARN only, per R1). Re-running the evaluator against a previously-cleared step
  will not cause a retroactive FAIL.

---

## 5. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-1 | Auth file with `reviewed_files:` listing at least one file present in the diff → condition 10 skipped, no compliance failure |
| AC-2 | Auth file with `reviewed_files:` listing only files not in the diff → condition 10 runs; evaluator reports which diff files triggered the signal and which listed files did not match |
| AC-3 | Auth file with absent `reviewed_files:` field → condition 10 runs; evaluator emits a COMPLIANCE WARN noting the missing field (grandfathered for legacy files, FAIL for new files per R1 graduated rollout — see R1 grandfathering note) |
| AC-4 | Auth file with empty `reviewed_files:` list → condition 10 runs |
| AC-5 | No auth file present → existing behavior; condition 10 runs and fires on a structural-override signature in the diff |
| AC-6 | A new auth file that lacks `reviewed_files:` → COMPLIANCE WARN (not FAIL) for the transition period; a new file with the field present and overlapping → passes |
| AC-7 | The orchestrator's ESCALATE block includes the `reviewed_files:` field in its file-creation example |
| AC-8 | The evaluator's condition-10 skip report identifies the overlapping file(s) it used to accept the skip |

---

## 6. Affected Artifacts

| Artifact | Change type | Summary |
|---|---|---|
| `contract/OVERSIGHT-CONTRACT.md` §1 | Additive | Document `reviewed_files:` as a required field in the human-authorization file format; note grandfathering for legacy files |
| `contract/OVERSIGHT-CONTRACT.md` §7 condition 10 | Clarifying | Replace "authorization file exists and is non-empty" skip logic with "authorization file has non-empty `reviewed_files:` overlapping the diff" |
| `.claude/agents/oversight-orchestrator.md` | Additive | Update CRITICAL STEP AUTHORIZATION REQUIRED example to include `reviewed_files:` field |
| `.claude/agents/oversight-evaluator.md` | Additive | Add enumeration-overlap check to the condition-10 skip logic in Phase 1 |

No new files are created. No existing compliance conditions are removed or reordered. Contract
version is not bumped (additive-only change per contract §8). The existing `human-authorization`
audit event (`audit/oversight-log.jsonl`) gains no new fields — it already records `content_sha256`
which will reflect whether the file contained the new field.
