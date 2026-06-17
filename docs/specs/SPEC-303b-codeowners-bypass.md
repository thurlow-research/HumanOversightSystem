# Requirements Spec — Issue #303 Finding 2: CODEOWNERS Bypass Gap

**Document type:** Requirements specification
**Status:** Draft — for technical-design
**Issue:** #303 (Finding 2 only)
**Companion:** `SPEC-overseer-merge-authority.md` (merge-authority decision logic)
**Date:** 2026-06-16
**Author:** pm-agent

---

## 1. Problem Statement

The overseer's merge-authority check enforces a HUMAN_REQUIRED gate on
"protected surfaces" (defined as paths in the evaluator's protected-surface list and
implemented in `require_human_approval.py`). However, CODEOWNERS paths that are NOT
on the protected-surface list have no reviewer restriction. Any collaborator with
Maintain or Write role — including the overseer bot account — can approve a PR touching
those paths.

Observed in the field (CPS field report #303, Finding 2): the human owner
`ScottThurlow` authored a PR touching `contract/`, which is a CODEOWNERS-protected
path owned by `@ScottThurlow`. No human other than the author was available to approve,
and the overseer account was excluded from CODEOWNERS but was not blocked from
approving non-CODEOWNERS-listed paths. The practical consequence of the gap: on a
different PR where the human is not the author, the overseer could approve paths whose
ownership intent was human-only.

The fix: the overseer must treat any CODEOWNERS entry mapped to a human account as
HUMAN_REQUIRED, not just paths already on the protected-surface list.

---

## 2. Scope

This spec covers the overseer's merge-authority check only. It does not cover:
- The branch protection ruleset configuration (that is a setup / org-migration concern
  addressed separately in #303 Finding 2's org migration checklist item).
- `require_human_approval.py` — that file enforces the protected-surface gate and
  does not need to be changed by this spec. The CODEOWNERS-derived gate is an
  additional check layered on top of it.
- Paths where CODEOWNERS lists a team rather than an individual. (See OQ-1.)

---

## 3. Definitions

**Protected-surface list:** The existing set of paths that `require_human_approval.py`
marks HUMAN_REQUIRED. Unchanged by this spec.

**CODEOWNERS human-owned path:** Any path pattern in the repo's CODEOWNERS file whose
owning entry resolves to one or more individual human GitHub usernames (i.e., entries
of the form `@username`, not `@org/team`). CODEOWNERS files supported by this spec are
the standard GitHub locations: `.github/CODEOWNERS`, `CODEOWNERS`, `docs/CODEOWNERS`,
checked in that priority order.

**Bot accounts:** The overseer account (`OVERSIGHT_ACCOUNT`, default
`HOSOversightTutelare`) and the worker account (`WORKER_ACCOUNT`, default
`HOSWorkerTutelare`). A CODEOWNERS entry that lists only bot accounts is not a
human-owned path for purposes of this spec.

**HUMAN_REQUIRED:** A verdict the overseer must emit when it cannot self-approve.
The overseer posts a comment, does not merge, and assigns to the human operator.

---

## 4. Functional Requirements

### R1 — CODEOWNERS parsing at merge-authority check time

Before the overseer decides to auto-approve or auto-merge a PR, it must:
1. Locate the repo's CODEOWNERS file (`.github/CODEOWNERS` preferred; fall back to
   `CODEOWNERS`, then `docs/CODEOWNERS`).
2. Parse it to build a map of path patterns to owner lists.
3. For each path pattern, determine whether any owner is a human account (i.e., not
   in the bot accounts set defined by `OVERSIGHT_ACCOUNT` and `WORKER_ACCOUNT`).

If no CODEOWNERS file exists, skip this check (log a note) and proceed with only the
existing protected-surface gate.

### R2 — PR diff vs. CODEOWNERS intersection

For each file changed in the PR, the overseer must evaluate whether that file matches
any CODEOWNERS pattern with a human owner. CODEOWNERS path matching follows GitHub's
documented rules: last matching pattern wins; `*` matches any file in the directory
but not subdirectories; `**` matches any file at any depth.

The overseer does not need to implement full gitignore-glob semantics. A conservative
approach — treating a match as any CODEOWNERS pattern that is a prefix of the changed
file path, or an exact match — is acceptable, provided it errs toward HUMAN_REQUIRED
rather than away from it. (See OQ-2.)

### R3 — HUMAN_REQUIRED on any CODEOWNERS-human-owned match

If any changed file in the PR matches a CODEOWNERS pattern whose owner list includes at
least one human account (after excluding bot accounts), the overseer must emit
HUMAN_REQUIRED for the entire PR. The overseer must not self-approve that PR.

This requirement holds regardless of whether the matched path is on the protected-surface
list. CODEOWNERS-derived HUMAN_REQUIRED is additive to, not a replacement for, the
existing protected-surface gate.

### R4 — Comment on HUMAN_REQUIRED due to CODEOWNERS

When the overseer emits HUMAN_REQUIRED as a result of this check (not the protected-surface
check), it must post a PR comment that:
- States the PR touches CODEOWNERS-human-owned paths.
- Lists the specific files that triggered the match and the owning entry from CODEOWNERS.
- States who must approve (the human owner listed in CODEOWNERS).
- Does not include the existing protected-surface HUMAN_REQUIRED message unless that
  check also fired independently.

### R5 — Bot account configuration

`OVERSIGHT_ACCOUNT` and `WORKER_ACCOUNT` environment variables override the defaults
(`HOSOversightTutelare` and `HOSWorkerTutelare`). The overseer must use the resolved
values when determining whether an owner is a human vs. bot.

### R6 — No merge without HUMAN_REQUIRED resolution

The overseer must not proceed to merge a PR flagged HUMAN_REQUIRED by R3, even if the
protected-surface gate would have passed. The existing protected-surface non-merge path
applies; this spec extends it to cover the CODEOWNERS case.

### R7 — Logging

The overseer must log:
- Whether a CODEOWNERS file was found and which location.
- The set of CODEOWNERS-human-owned paths matched by the PR diff (may be empty).
- The resulting gate decision (auto-proceed or HUMAN_REQUIRED) and which check triggered it.

---

## 5. Non-Requirements

- This spec does not require the overseer to post a review dismissal on already-posted
  approvals from other accounts.
- This spec does not change branch protection ruleset configuration. The CODEOWNERS check
  is implemented in the overseer's merge-authority logic, not as a GitHub ruleset.
- This spec does not address paths owned by `@org/team` entries. Those are deferred
  (OQ-1).
- This spec does not require the overseer to validate that the human listed as CODEOWNERS
  owner actually has permission to approve the PR on GitHub. That is a setup concern.

---

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-1 | PR touching only non-CODEOWNERS paths: overseer merge-authority check unchanged |
| AC-2 | PR touching a CODEOWNERS path owned by a human: overseer emits HUMAN_REQUIRED |
| AC-3 | PR touching a CODEOWNERS path owned only by bot accounts: not flagged by this check |
| AC-4 | PR touching a CODEOWNERS path on the existing protected-surface list: HUMAN_REQUIRED (both checks may fire; only one HUMAN_REQUIRED verdict is emitted) |
| AC-5 | No CODEOWNERS file present: check skipped, logged, no regression to existing behavior |
| AC-6 | OVERSIGHT_ACCOUNT and WORKER_ACCOUNT overrides are respected |
| AC-7 | HUMAN_REQUIRED comment lists the triggering files and CODEOWNERS entries |
| AC-8 | Overseer does not merge a CODEOWNERS-HUMAN_REQUIRED PR regardless of protected-surface check outcome |

---

## 7. Open Questions for Architect

**OQ-1 — Team entries in CODEOWNERS.**
The issue is silent on whether `@org/team` entries should be treated as human-owned.
For a team that contains only humans, the answer is probably yes. But resolving team
membership requires an additional GitHub API call. Current scope treats team entries as
out of scope (not matched by this check). Architect should confirm or extend.

**OQ-2 — CODEOWNERS pattern matching fidelity.**
Full gitignore-glob semantics (negation, `**`, character classes) are non-trivial to
implement in bash or Python without a library. A conservative prefix/exact-match approach
errs toward HUMAN_REQUIRED and is safe. Architect should decide whether to use a library
(`gitpython`, `codeowners` PyPI package) or implement conservative matching, and document
the residual false-positive surface.

**OQ-3 — Implementation location.**
The issue references `require_human_approval.py` as the existing protected-surface
enforcer. The architect should decide whether the CODEOWNERS check is added to that file,
to the overseer agent logic directly, or to a new dedicated module. This spec is neutral
on implementation location.

**OQ-4 — CODEOWNERS file caching.**
If the overseer runs the merge-authority check multiple times per session (e.g., on
PR update events), should it re-read CODEOWNERS each time or cache it? The architect
should specify the caching strategy to avoid stale state if CODEOWNERS is updated
between checks.
