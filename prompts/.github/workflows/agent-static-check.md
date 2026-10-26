# Prompt Artifact — agent-static-check.yml

| Field | Value |
|---|---|
| **Generated file** | `.github/workflows/agent-static-check.yml` |
| **Description** | Replace validation-stamp CI check with direct agent static check (#2053 slice 1, Option A) |
| **Date** | 2026-10-15 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Worker → `coder` brief (condensed faithfully; full text in the worker session transcript):

```
Implement slice 1 of #2053 on branch worker-2053-retire-validation-stamps-261015080501-1126855.
Human ruling Option A (confirmed 2026-10-15): replace the stamp check with a CI job
that runs `bash scripts/framework/check_agents_static.sh` directly on the PR head;
keep it NON-required. Verified: the script exits 0 / 0 findings on current main.

1. Delete .github/workflows/validation-check.yml. Add .github/workflows/agent-static-check.yml
   (name "Agent Static Check", job agent-static-check / "Agent static checks"; pull_request to
   main; paths .claude/agents/**, docs/**, scripts/**, bootstrap/**, bin/**, the workflow itself
   [superseded in v3: the final workflow has NO paths filter — see Refinement History];
   checkout@v4; run the script). Header: replaced the stamp check per #2053 Option A; deliberately
   not required (setup_branch_protection.sh contexts, merge_authority #1580); HOS-internal.
2. Delete scripts/framework/check_validation_current.sh.
3. check_agents_static.sh: remove the phase1 stamp-writing block; fix header to list all 9 checks.
4. framework_consumer_files.txt: stop shipping validation-check.yml; drop the deleted script from
   the NOT-shipped comment; do not ship the new workflow. Report consumer-upgrade orphan behaviour.
5. test_consumer_framework_files.py: drop check_validation_current.sh from _HOS_DEV_ONLY.
6. Add tests/framework/test_agent_static_check_workflow.py (old files gone; workflow runs the script,
   no stamp ref; not consumer-shipped; not a required context; clean run writes no stamp).
7. Update docs/CI-EXECUTION-INVENTORY.md and docs/GENERATED-ARTIFACTS.md minimally.
8. Regenerate SCRIPTS-INDEX.md; regen_all.sh --check must pass.
9. Append dated DECISIONS.md entry recording the ruling, reason, non-required status, #1536 narrowed.
Out of scope: committed *.stamp files, .gitattributes, other stamp writers, cut_release.sh,
regen_all.sh, secret_scan stamp skip, README/METHODOLOGY/historical docs.
Do not edit .claude/agents/ (worker session does that). No closing keywords; "Refs #2053".
```

## Constraints Specified

- Non-required CI job; must not enter branch-protection contexts or merge_authority's required set.
- HOS-internal: not shipped to consumers (check_agents_static.sh is HOS dev-only).
- Must NOT: edit `.claude/agents/`, push, touch GitHub, delete stamps or other writers (later slices).

## Refinement History

v1: brief above. The new check's first run flagged `.claude/agents/overseer.md:458` (dangling ref to the
deleted script); the worker session rewrote that note directly (agent-definition edits are never delegated).
v2: follow-up brief — check 9 scans every `*.md` repo-wide but the trigger covered only `docs/**`; add
`'**.md'` to `paths:` plus a test asserting it.
v3: risk-assessor brief items — add a least-privilege `permissions:` block; correct README.md's stale
stamp-enforcement claim. Code review S1: drop the `paths:` filter entirely (check 3 can fail on a
deleted referenced file anywhere in the repo; a non-required job gains nothing from a filter); a
test asserts there is no paths/paths-ignore. **Final state: no paths filter.**
v4 (worker session, overseer.md only): code review M1 and agy second-review findings — the overseer
folds the `Agent static checks` run into its step 2a check-runs read (absent defers, stall guard
applies, any non-success conclusion is DIRTY) instead of calling a library function.

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
3. Compare key logic paths against `.github/workflows/agent-static-check.yml`
4. Note any drift in a new version artifact (`agent-static-check.v1.md`)
