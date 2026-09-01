# Prompt Artifact — merge_authority.py (NG3b release-detection precision, #1032)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/merge_authority.py` (+ `tests/automation/test_phase_b.py`) |
| **Description** | Split the NG3b release heuristic into title patterns and path globs so milestone docs paths stop false-positiving |
| **Date** | 2026-07-27 |
| **Model** | claude-sonnet-4-6 |
| **Risk level** | MEDIUM (governance / merge-authority logic) |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Fix #1032: _is_release_related() in scripts/automation/lib/merge_authority.py
concatenates pr_title with every changed path into one string and substring-matches
a flat keyword list (_RELEASE_PATTERNS). The list contains "v0.", "v1." and "tag",
so any path under docs/v0.6.0/** — and any path containing "staging"/"metadata" —
is read as a release. Observed on PR #1031 (docs-only ADR): decide_merge_authority()
returned HUMAN_REQUIRED with reason "Release-related PR — autonomous releases are
prohibited (NG3b)" for a PR touching no release artifact.

Split the heuristic into two independent matchers:

1. Title patterns — word-boundary regex, not substring: release/releases/releasing,
   publish(es|ed|ing), ship(s|ped|ping), semver, tag(s)/tagging, and vN.N[.N]
   version strings. Word boundaries are what kill the "staging"/"metadata" class
   of false positive.

2. Path globs — fnmatch against release artifacts only: docs/releases/**,
   .hos-release, CHANGELOG*, release/v*. Match each pattern both bare and with a
   "**/" prefix, mirroring _touches_protected_surface().

Do NOT reuse the whole of scripts/framework/protected_surfaces.txt as the path
list, even though the issue suggests it: that file covers every control surface
(bin/**, .claude/agents/**, contract/**, …), so reusing it would label unrelated
control-surface PRs as releases and widen NG3b with a misleading reason. Those
surfaces are already gated separately by _touches_protected_surface(). Keep an
explicit release-artifact list and comment the sync relationship to the
"Release artifacts (#761)" block of protected_surfaces.txt.

Pin regression tests in BOTH directions in tests/automation/test_phase_b.py:
- True: docs/releases/v0.5.1.md, .hos-release, CHANGELOG.md, release/v0.6.0, and
  titles containing cut release / tag v0.6.0 / publish / semver.
- False: docs/v0.6.0/** docs, packs/** paths containing "tag", metadata-bearing
  paths, and the exact #1032 reproducer
  _is_release_related("docs(adr): ADR-032 …",
                      ["docs/v0.6.0/ADR-032-astro-js-support.md", "DECISIONS.md"]).
Plus decide_merge_authority()-level tests: the milestone-docs PR is not is_release,
and a genuine release PR is still HUMAN_REQUIRED + needs-human.

Constraint: this is a precision fix only. The change may only ever REMOVE false
positives; it must not enable an autonomous release path or weaken any other guard.
Match the surrounding code and test idiom.
```

## Constraints Specified

- **Direction of change:** narrowing only — the guard may lose false positives, never gain an autonomous-release path.
- **Independence:** title matched against title, paths matched against paths; never concatenated.
- **Word boundaries:** the mechanism that fixes the `tag`/`staging`/`metadata` class of false positive.
- **No list reuse:** `protected_surfaces.txt` is deliberately *not* reused as the release-path list (would widen NG3b to every control surface with a wrong reason); the two lists are kept in sync by comment.
- **Backstop preserved:** genuine release artifacts remain on the server-side protected surface (#761), so a heuristic miss still gates.
- **Bidirectional test pinning:** true positives and false positives both asserted.

## Refinement History

First attempt — design taken from the issue's suggested fix, with one deliberate
deviation: the issue proposed reusing `protected_surfaces.txt` for path patterns;
that would have widened the NG3b escalation path to every control surface, so an
explicit release-artifact glob list was used instead. Deviation flagged in the PR.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by:
     - Date reviewed:
     - Findings:
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `scripts/automation/lib/merge_authority.py`
   (`_RELEASE_TITLE_RE`, `_RELEASE_PATH_GLOBS`, `_matches_release_path`,
   `_is_release_related`) and the `#1032` tests in
   `tests/automation/test_phase_b.py` (`TestIsReleaseRelated`,
   `TestReleaseGuardDecision`)
4. Note any drift in a new version artifact
   (`merge_authority-ng3b-precision.v2.md`)
