# Finding: Human Workflow Intuition as the Routing Heuristic for Agent Artifact Placement

**Role:** oversight-mechanism — routing a finding to the channel that actually blocks

**First observed:** 2026-06-12, documentation session on ARCHITECTURE.md agent contract table  
**Documented in:** ARCHITECTURE.md — "Findings routing: issues vs. PR threads"

---

## The Finding

AI agents that produce review findings must decide where to place them: GitHub issues or PR threads. The naive choice — always use issues for a complete audit trail — produces noise that degrades the issue tracker and creates orphaned work items when feature branches are abandoned. The naive alternative — always use PR threads — loses findings that the risk-historian needs for longitudinal analysis and discards project-level concerns that survive branch merges.

The routing heuristic that resolves this:

> **Would a human doing this work in the inner loop file a GitHub issue?**

A developer reviewing a PR does not open issues for "add a test here" or "this function needs a null check." Those are PR comments — they live and die with the PR. The same developer absolutely would open an issue for "this auth boundary is wrong across the system" or "the spec doesn't cover this edge case." Agents follow the same convention.

---

## The Routing Table

| Finding type | Route | Rationale |
|---|---|---|
| `spec-gap` | Issue | Transcends branches; affects future sessions and specs |
| `security-finding` (crit/high) | Issue | Project-level; feeds risk-historian; may recur |
| `privacy-finding` (blocking) | Issue | Regulatory concern; tracked across project lifecycle |
| `design-concern` | Issue | Architectural decision; affects future build steps |
| `red-team-finding` (crit/high) | Issue | System-level; must survive branch lifecycle |
| Test coverage failures | PR thread | Inner-loop correction; closes with PR |
| System test failures (session-local) | PR thread | Fixable in current session; no cross-branch relevance |
| Code reviewer findings | PR thread | Developer-to-developer correction; not a work item |
| UI/a11y/infra reviewer findings | PR thread | Inline correction; not a tracked project concern |
| System test failures (persistent/spec) | Issue | Escalated: survives session boundary; affects spec |

---

## The Branch Context Problem

Issues are repo-scoped, not branch-scoped. An issue filed during a feature session refers to code that only exists on a branch. If the branch is abandoned, the issue lingers with no context. If it merges, the issue's branch reference is lost.

The mitigation: every issue created by an agent carries `Branch:` and `PR:` fields in the body. This is enforced as a convention in `run_red_team.sh` and specified in ARCHITECTURE.md. It does not fully solve the lifecycle problem (an abandoned-branch issue still persists) but makes the temporal context explicit for future readers.

The deeper fix — automatically closing issues when their source branch is abandoned — is not yet implemented. It would require a branch-deletion webhook that queries open issues by branch name and closes them with a note.

---

## Why the Risk-Historian Dependency Matters

The `risk-historian` agent queries GitHub issues to build historical bug density for changed files. This is the mechanism that makes the pipeline's risk scoring improve over time — early sessions have no history; later sessions accumulate a bug density signal that calibrates the risk-assessor's output.

This dependency creates a hard constraint: findings that should inform future risk scoring **must** be issues, not PR threads. A security finding buried in a closed PR's review thread is invisible to risk-historian. If agents routed all findings to PR threads for simplicity, the risk-historian would never accumulate data, and the pipeline's longitudinal calibration would fail silently.

The routing distinction is therefore not just about noise management — it is a data pipeline requirement.

---

## Implications for Research

1. **Mimicking human workflow conventions reduces friction and improves artifact hygiene.** Agents that follow the same artifact conventions as human contributors (issue for project concern, comment for inline correction) produce outputs that fit naturally into existing team workflows. The heuristic "would a human file an issue?" is cognitively accessible and consistently applicable without enumeration of every case.

2. **Audit trail design must account for artifact lifecycle, not just completeness.** A complete audit trail that includes every finding is less useful than one where findings are routed to the artifact type with the appropriate lifecycle. An issue that survives branch abandonment with context is more valuable than a PR thread that closes silently and more honest than an issue with no branch reference.

3. **Pipeline longitudinal calibration requires a queryable finding store.** The risk-historian pattern — querying issues for historical bug density — only works if the issue tracker is a reliable signal. Routing all findings to issues would add noise; routing all to PR threads would starve the signal. The routing heuristic is the mechanism that keeps the issue tracker as a meaningful data source for pipeline calibration.

4. **Branch context stamping is a lightweight provenance mechanism.** Adding `Branch:` and `PR:` to every agent-created issue costs nothing and makes cross-branch analysis tractable. This is a specific instance of the broader pattern: any artifact created during a session should carry enough context to be interpretable after the session ends and the branch is gone.

---

## Related findings

- `stamp-based-ci-enforcement.md` — committed artifacts as a CI enforcement primitive; the stamp file is a related pattern where artifact lifecycle maps to code lifecycle
- `risk-historian-cold-start.md` — how the risk-historian accumulates signal from issue history (to be written)
