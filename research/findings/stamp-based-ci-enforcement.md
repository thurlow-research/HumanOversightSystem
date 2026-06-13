# Finding: Committed Timestamp Files Bridge Local-Only Validation Tools and CI

**First observed:** 2026-06-12, session `2026-06-12-ux-designer-validation-suite.md` (Part 3)
**Demonstrated:** PR #13 on HumanOversightSystem, three consecutive pushes

---

## The Finding

When a validation pipeline includes tools that cannot authenticate in CI — such as subscription-based AI reviewer CLIs (agy, codex) that require local browser OAuth — the standard approach of "run everything in the CI pipeline" is not available. A committed timestamp file provides a practical bridge: the developer runs validation locally, the result is committed as a structured artifact, and CI checks only that the artifact is current relative to the code changes.

The specific mechanism:
1. Each validation script writes a timestamp file on success to a tracked directory (`scripts/framework/validation-stamps/`)
2. The top-level runner writes a combined `all-phases.stamp` only when all enabled phases pass
3. The CI check reads the **git commit timestamp** of the stamp file and compares it against the git commit timestamps of all changed files in the PR
4. If any changed non-excluded file was committed after the stamp → CI fails

This does not re-run the AI validation in CI. It verifies that the developer ran it before pushing.

---

## Why Git Commit Timestamps, Not Filesystem Mtime

Filesystem modification times (`mtime`) are reset when a repository is cloned or checked out. A CI runner that clones the repository sees all files with the same mtime (the time of the clone), making mtime comparisons meaningless in a CI context.

Git commit timestamps are part of the immutable repository history. They are stable across clones, checkouts, and CI runners. The comparison `file_commit_time > stamp_commit_time` is reliable regardless of where the check runs.

---

## What the Pattern Enforces

The stamp pattern enforces a specific developer workflow: validation must be the last action before committing. Any code change committed after the stamp (without revalidating) makes the stamp stale, and CI fails. The developer must rerun validation and commit the updated stamp alongside — or as the last commit in — their push.

**Workflow it enforces:**
```
make changes → run validation → commit (changes + stamp together) → push → CI passes
```

**Workflow it rejects:**
```
make changes → run validation → commit stamp → make more changes → commit changes → push
                                                ↑ stamp now predates the new changes → CI fails
```

**Edge cases handled correctly:**
- Changes and stamp committed in the same commit: same git timestamp → passes (check is strictly greater-than)
- Changes committed first, stamp committed second: stamp timestamp > changes → passes
- `git commit --amend` on a commit containing both: resets all timestamps to "now" → still passes
- `--static-only` run: `all-phases.stamp` is written with `skipped:` field noting AI phases were skipped; CI check still passes (it checks currency, not completeness — completeness is enforced by the "never skip" governance rule)

---

## The "Skipped Phases" Nuance

The stamp records which phases ran and which were skipped. The CI check only verifies currency (stamp ≥ changed files), not completeness (all phases ran). The governance rule that skipping phases requires human approval is enforced by agent behavior and process, not by the CI check.

This is an intentional design choice: making the CI check strict enough to require all four phases would mean any `--static-only` run (a common fast-path) would fail CI. The two-layer enforcement — CI for currency, governance process for completeness — keeps CI fast while maintaining the governance intent.

---

## Excluded Paths

Some categories of change do not require revalidation:
- `audit/` — append-only oversight log; changes do not affect agent or doc correctness
- `research/` — research notes; changes are additive documentation, not framework changes
- `.claudetmp/` — ephemeral working files; not tracked in git
- `scripts/framework/validation-stamps/` — the stamps themselves; circular otherwise

The exclusion list is maintained in `check_validation_current.sh` and should be updated when new categories of non-framework content are added.

---

## Demonstrated Efficacy

Three consecutive pushes to PR #13 confirmed the mechanism:

| Push content | Stamp vs. changed files | CI result |
|---|---|---|
| Framework code + stamp (same commit) | stamp_time == file_time | ✅ pass (6s) |
| `README.md` touched, no revalidation | README newer than stamp | ❌ fail (6s) |
| Stamp updated, committed last | stamp_time > README_time | ✅ pass (6s) |

CI check runs in ~6 seconds. No AI models invoked. The entire check is a git log lookup and timestamp comparison.

---

## Implications for Research

1. **Committed artifacts as a CI enforcement primitive.** The stamp file is a specific instance of a general pattern: when CI cannot reproduce a process (because the process requires local auth, local hardware, or human judgment), a committed artifact can serve as a proxy that proves the process ran. The artifact's currency relative to code changes is checkable without re-running the process.

2. **The two-layer governance model for non-reproducible processes.** The stamp-based check enforces *currency* (was it run recently?); the governance process (agent behavior, memory rules, decisions.md) enforces *completeness* (were all phases run?). Neither layer alone is sufficient: currency without completeness allows --static-only to satisfy CI; completeness without currency allows developers to run validation once and never again.

3. **Tooling constraints shape governance architecture.** The decision to run AI validation locally (due to subscription auth) forced the stamp pattern. A team using API-key-based AI services could run phases 2–4 directly in CI. The stamp pattern is specifically optimized for the subscription CLI model where auth is local. This is worth noting for research on how tooling choices propagate upward into governance architecture.

4. **Git's immutable history as a lightweight audit trail.** The stamp file committed to git is part of the permanent repository history. It records not just that validation passed, but when, which phases ran, and what was skipped — linked by commit hash to the exact state of the codebase at that point. This gives an audit trail of validation history without any external database or logging infrastructure.

---

## Related findings

- `tooling-drift-in-validation-pipelines.md` — what happens when the tools the stamp depends on change their APIs
- `self-governance-recursion.md` — the framework governing its own development, of which this CI check is a component
- `cross-vendor-review-finds-real-bugs.md` — the local validation phases that the stamp represents
