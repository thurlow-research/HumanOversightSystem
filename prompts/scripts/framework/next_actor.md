# Prompt Artifact — next_actor.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/framework/next_actor.py` (also `.github/workflows/needs-human-assign.yml`, `.github/workflows/label-swap.yml` glue, `docs/LABELS.md`, tests) |
| **Description** | needs-human assignment primitive + label-event workflow (#2224) |
| **Date** | 2026-11-05 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | HIGH |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Autonomous worker cycle, no human present. Repo: <worker-clone-root>,
branch worker-2224-needs-human-assign-261105215001-2050340 is checked out.
Do NOT run git checkout, git stash, git commit, or switch branches; do not file issues or
change labels; do not edit .claude/agents/**.

Implement issue #2224 exactly as specified by the approved technical design
docs/v0.7.0/TECHNICAL-DESIGN-2224-needs-human-assign.md, which implements the architect's
addendum docs/v0.7.0/ADR-2224-needs-human-assign-workflow.md (amending
docs/v0.7.0/ADR-1928-next-actor-assignment.md AD-1/AD-3/AD-5). The TD is the contract:
file list, CLI, exit codes, gh api call sequence, assigner classification, workflow YAML,
label-swap.yml glue lines, LABELS.md text, and the named test list.

Requirements beyond the TD's text:
- Ask (report back) rather than guess if the TD is ambiguous on anything load-bearing.
- Keep the string PATCH out of next_actor.py entirely (docstrings and comments too), as the
  static test bans it in the source.
- No ${{ }} interpolation of untrusted event fields inside any run: block; event data
  reaches the script only via env:.
- Write all the tests named in the TD; tests use a fake gh and must be deterministic and
  leave no temp files behind (tests/conftest.py enforces TMP_HYGIENE).
- Run: scripts/oversight/.venv/bin/python -m pytest tests/framework/test_next_actor.py
  tests/framework/test_needs_human_assign_workflow.py -q, and the existing tests touching
  docs/LABELS.md and label-swap.yml, and report results.
- Regenerate SCRIPTS-INDEX.md with scripts/framework/gen_scripts_index.sh.
- Emit the CORE self-flag (RISK / CONFIDENCE / BLAST RADIUS) at the end.
```

The literal prompt named the Worker clone's absolute path; it is recorded here as
`<worker-clone-root>` so the artifact carries no machine-specific path (portability gate).
Two later fix rounds (code-review/prompt-fidelity round 1, reliability round 2) are
recorded in the branch's commit messages and the TD errata section.

## Constraints Specified

- Runtime: Python stdlib + `gh` CLI on a GitHub-hosted runner; no `scripts/automation/lib/` import.
- Security: no PR-head checkout; `persist-credentials: false`; add-only `POST /assignees`; never a list-replacing assignee write; never writes labels; refuses on `release-request` at a live re-read; refuses when `HUMAN_REVIEWER` is empty/bot/unassignable; `HUMAN_REVIEWER` only from the trusted checkout's `machine-accounts.env`.
- Must NOT: backfill existing `needs-human` items; read `actor` to classify assignments; remove any assignee other than `HUMAN_REVIEWER`.

## Refinement History

Delete this section if first attempt worked.

## Human Review Notes

<!-- After human review, record findings here. -->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `scripts/framework/next_actor.py`
4. Note any drift in a new version artifact (`next_actor.v1.md`)
