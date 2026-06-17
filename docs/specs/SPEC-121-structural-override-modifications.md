# SPEC-121: Structural Override — Modification Detection for Existing Signatures
**Issue:** #121
**Status:** Draft — for architect review
**Target milestone:** v0.4.0 — Autonomous Worker
**Related spec:** `docs/specs/SPEC-evaluator-re-derivation.md` §4 (consolidated multi-issue treatment; see that document for the full requirement set including acceptance criteria and open architect questions)

---

## Problem Statement

`change_classifier.py` detects structural-override signatures — new auth checks, new routes, new permission states, new external dependencies, new template files — and forces `structural` classification regardless of how the authoring agent labeled the change (contract §2a). The oversight evaluator invokes the classifier during Phase 1 to re-derive structural signals from the diff (condition 10).

The current detection logic checks for **additions only**: new lines matching structural patterns, or new files added to the tracked template set. It does not detect **modifications to existing structural signatures**. A change that modifies an existing auth decorator, weakens an existing permission gate, removes an authentication requirement from an existing route, or alters the required role in an existing permission check does not trigger the structural-override signal — even though it changes security-relevant behavior that the original structural signal was supposed to protect.

Specific examples cited in the Opus/codex review findings:

- `@require_permission('admin')` changed to `@require_permission('user')` on an existing view: weakens a permission gate, but no new permission check was added, so `new-permission-or-auth-state` does not fire.
- `@login_required` removed from an existing route: the route existed before (so `new-user-flow-or-route` does not fire), and the auth check was existing (so `new-permission-or-auth-state` does not fire). The removal of a security boundary is invisible to the current classifier.
- A spec or design document's `## Authorization` section is modified to reduce the set of required approvals: no signature-bearing addition occurred, so nothing forces `structural`.

Contract §2a already documents this as a "Residual coverage gap": the mechanical signatures detect additions; modifications to existing behavior rely on "honest self-classification plus reviewer/panel detection." This spec narrows that gap for two specific, mechanically detectable classes: (1) modifications to existing auth/permission decorators and middleware in application code, and (2) modifications to structural sections of committed design and spec documents.

---

## Scope

This spec covers:

- Extending `change_classifier.py` to track removed lines from the diff alongside added lines (the `collect_diff` function currently returns only `added_lines_by_file`).
- Detecting modifications to existing auth/permission decorators in application code: a diff that both removes and re-adds a structural auth pattern on the same file signals a modification to an existing auth boundary.
- Detecting modifications to existing structural sections in committed spec and design documents: a diff that both removes and adds lines in a security/permission-bearing section of a tracked document.
- Extending the evaluator Phase 1 to run modification detection and enforce the same human-authorization requirement as condition 10 for uncovered modifications (new compliance condition 14).
- A new `doc-modification-uncovered` audit event in `audit/oversight-log.jsonl`.

This spec does not cover:

- Detection of modifications to existing routes (adding/removing path arguments, changing URL patterns on existing routes). The modification surface for routes is large and the false-positive rate would be high; this is deferred.
- Detection of modifications to dependency versions (changing a pinned version of an existing dependency). Version changes carry risk but the classification boundary between patch/minor/major is not deterministic from the diff alone; this is deferred to a follow-on issue.
- Changes to application logic that modify effective permission behavior without touching the auth decorator itself (e.g., changing the body of a view that is already protected). This class remains in the "honest self-classification plus reviewer" category documented in contract §2a; it is not mechanically detectable.

---

## Requirements

**R1 — Track removed lines in `collect_diff`.**

The `collect_diff(base, head)` function in `change_classifier.py` must be extended to return `removed_lines_by_file` (a dict mapping file path to list of removed content lines, without the leading `-`) alongside the existing `added_lines_by_file`. Removed lines are those beginning with `-` in the unified diff output, excluding `---` file-header lines.

The function signature must become:
```python
def collect_diff(base, head) -> tuple[list[tuple[str, str]], dict[str, list[str]], dict[str, list[str]]]:
    """Return (name_status, added_lines_by_file, removed_lines_by_file)."""
```

All existing callers within `change_classifier.py` must be updated to handle the new return value. The change is backward-compatible at the CLI level (no new required flags).

**R2 — Detect modifications to existing structural signatures (`detect_structural_modifications`).**

`change_classifier.py` must implement a `detect_structural_modifications(name_status, added, removed) -> list[dict]` function that identifies two categories of potentially-structural modifications:

**Category A — Auth/permission decorator modifications in application code.**

A modification is detected when, for the same file:
- At least one removed line matches a structural auth/permission pattern (the existing `ADDED_LINE_SIGNATURES` patterns for `new-permission-or-auth-state`), AND
- At least one added line also matches the same pattern, AND
- The removed and added lines are not identical (i.e., the decorator was changed, not just moved).

This detects a change to an existing auth boundary: the check existed before and still exists after, but with different parameters. The signal name is `modified-permission-or-auth-state`.

The `FRAMEWORK_TOOLING` exemption applies to this check: files under `scripts/oversight/` or `scripts/framework/` are excluded from application-domain pattern scanning.

**Category B — Modifications to structural sections of design/spec documents.**

The tracked document patterns and structural section markers are:

| Document pattern | Structural section markers |
|---|---|
| `docs/specs/SPEC-*.md`, `docs/v*/SPEC-*.md` | Any section containing the words (case-insensitive): `permission`, `authorization`, `auth`, `approval`, `gate`, `required`, `must`, `shall`, `deny`, `block`, `restrict` |
| `docs/v*/TECHNICAL-DESIGN-*.md`, `TECHNICAL-DESIGN-*.md` | Any section containing the words: `permission`, `authorization`, `auth`, `gate`, `access control`, `security`, `input validation`, `sanitiz` |
| `docs/v*/DESIGN*.md`, `DESIGN.md` | Any section containing the words: `permission`, `authorization`, `auth`, `gate`, `access control` |
| `TELEMETRY-SPEC.md`, `docs/ops/TELEMETRY-SPEC.md` | Any section header (all sections are structural) |

A modification to a structural section is defined as: a diff for a tracked document that both removes at least one line from a structural section AND adds at least one line to the same section. A purely additive change to a structural section (lines added, none removed) does not trigger this signal — purely additive changes in spec documents are handled by condition 10 (new-permission-or-auth-state) if a structural auth pattern was added. The signal name is `modified-doc-structural-section`.

The structural section determination is based on the nearest preceding `##` or `###` section header in the diff context. If no section header is parseable from the diff context, the file-level match is used as the section label.

**R3 — Evaluator Phase 1 compliance check (condition 14) and `--modifications-only` CLI flag.**

`change_classifier.py` must accept a `--modifications-only` flag that emits:
```json
{
  "structural_modifications": [
    {"signal": "modified-permission-or-auth-state", "file": "...", "section": null, "evidence": "..."},
    {"signal": "modified-doc-structural-section", "file": "...", "section": "## Authorization", "evidence": "..."}
  ]
}
```

The oversight evaluator, during Phase 1 compliance check, must:

1. Run `change_classifier.py --modifications-only --base <BASE_SHA> --head <HEAD_SHA>`.
2. For each detected `structural_modification`, check whether a covering human-authorization artifact exists: `.claudetmp/oversight/step{N}-human-authorization.md` or a domain-specific structural auth file (`.claudetmp/oversight/step{N}-spec-structural-auth.md`).
3. If any modification is not covered by such an artifact: **COMPLIANCE FAIL** (condition 14). The failure message must list the document file, the section title or nearest header, the removed line and added line characterizing the modification, and which artifact was checked.

Condition 14 runs **only in the loosening direction**: if the change was already classified `structural` by the authoring agent AND a covering human-authorization artifact exists, the check is skipped. If the `step{N}-human-authorization.md` file carries a `reviewed_files:` enumeration (SPEC-267) that overlaps the diff, the check is also skipped for those files.

**Audit event `doc-modification-uncovered`:** When condition 14 fires, the evaluator must append:
```json
{
  "event": "doc-modification-uncovered",
  "step": <N>,
  "file": "<path>",
  "section": "<section title or null>",
  "evidence": "<removed line / added line summary>",
  "timestamp": "<ISO-8601>"
}
```

---

## Non-Requirements

- This spec does not change how existing `new-*` structural signals are detected. The `ADDED_LINE_SIGNATURES` patterns and their enforcement in condition 10 are unchanged.
- This spec does not require detecting modifications to existing routes or existing dependency versions. Those classes are out of scope for this issue (see Scope section).
- This spec does not require detecting all possible ways a modification could weaken security. The modification-detection surface is intentionally narrow: auth/permission decorator changes on the same file, and structural section changes in tracked documents. The over-detect bias applies: false positives (a change to a comment in an auth section) are acceptable; false negatives are the real failure.
- This spec does not change the `human-tier-override.md` or `gate-suspension.md` mechanisms.

---

## Artifact Changes

| Artifact | Required change |
|---|---|
| `scripts/oversight/change_classifier.py` | Extend `collect_diff` to return `removed_lines_by_file`; add `detect_structural_modifications()`; add `--modifications-only` CLI flag; update all `collect_diff` callers |
| `.claude/agents/oversight-evaluator.md` | Add Phase 1 condition 14 check (after the existing condition 10 structural-override check) |
| `contract/OVERSIGHT-CONTRACT.md` | Add condition 14 to §7; update §2a "Residual coverage gap" note to reflect the narrowed gap; add `doc-modification-uncovered` to the §6a event catalog |

---

*Status: Draft — for architect review*
*Author: pm-agent | 2026-06-17*
