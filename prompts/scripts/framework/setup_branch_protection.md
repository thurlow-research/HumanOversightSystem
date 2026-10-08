# Prompt Artifact — setup_branch_protection.sh

| Field | Value |
|---|---|
| **Generated file** | `scripts/framework/setup_branch_protection.sh` |
| **Description** | Consumer-safe required-context split (#1981) |
| **Date** | 2026-10-07 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Prompt given by the autonomous worker to the `coder` subagent (abridged
only where it repeated file paths; all requirements verbatim in substance):

```
Implement issue #1981 on the checked-out branch. Do not branch, commit, push,
file issues, comment, or change labels.

Problem: scripts/framework/setup_branch_protection.sh ships to consumers
(framework_consumer_files.txt:64). Its literal "contexts" array requires 11
contexts, but only require-overseer-approval, require-human-approval and
require-tier-ceiling have producing workflows that ship. The other eight
(tests, oversight-gate-repo-scoped, oversight-gate-lint,
oversight-gate-type-check, oversight-validator-python,
oversight-validator-migration, oversight-validator-shell,
oversight-validator-diff-size) come only from HOS-repo workflows, so a
consumer gets required checks that never report (#737).

Binding design (architect-ruled, do not redesign):
TECHNICAL-DESIGN-1542-S1-detector-baseline.md §9.3 and §13.4 T-RP-05/T-RP-09.
1. New HOS-only scripts/framework/hos_required_contexts.txt: header comment;
   one name per line; blank/# ignored; names match ^[A-Za-z0-9._-]+$; the
   eight contexts in existing order; NOT in framework_consumer_files.txt; do
   not add sandbox-detector/sandbox-coverage (#1542 PR 2).
2. setup_branch_protection.sh: literal array keeps only the three core
   contexts (one line, same shape). Read the file if present BEFORE any API
   call (before the gh api user pre-flight); invalid line -> die naming it.
   Render valid names as ', "<name>"' fragments in a set -u-safe variable
   appended inside the array. Absent file -> nothing appended. Derive every
   human-facing listing (header, echo, trailing info) from the effective
   list; --dry-run prints the full list marking file-sourced entries. Move
   the HOS-only producer rationale (rulings/dates/issue refs, preserved)
   next to each name in the .txt; add a #1981 note.
3. tests/framework/test_branch_protection_contexts.py: _core_contexts(),
   _hos_only_contexts(), _required_contexts() = union so existing tests
   cover both. New: every core context is produced by a workflow listed in
   framework_consumer_files.txt (cite #1981); the .txt is absent from the
   ship list and from bootstrap/hos_install.sh; lines match the pattern, no
   duplicates, core/hos-only disjoint. Behavioural tests with a stub gh on
   PATH and a temp machine-accounts.env: no file -> only core; valid file ->
   appended names; invalid line -> non-zero exit with zero gh invocations;
   non-dry-run captured PUT payload contexts == core + file in order.

Constraints: tests must pass; shellcheck / black / isort clean on touched
files including pre-existing issues; touch only these three files; end with
the AGENTS.md self-flag.
```

## Constraints Specified

- Bash 4, `set -euo pipefail`, existing script helper/colour conventions.
- Security: the HOS-only file is validated against `^[A-Za-z0-9._-]+$` and
  rejected before any `gh` call, so it cannot inject JSON into the payload.
- Must NOT ship the HOS-only file to consumers, and must NOT change the HOS
  repo's effective required-context list (still 11, same order).
- Must NOT add the #1542 sandbox contexts.

## Refinement History

- v1: the prompt above.
- v2 (gate-driven): `bash_check` flagged `mapfile` (Bash 4+). Follow-up
  prompt: replace it with a Bash-3.2-safe here-string read loop; capture the
  payload JSON parse with `|| die` so a malformed payload or missing python3
  refuses to apply instead of PUTting silently; guard empty-array expansion
  under `set -u`; add a test for the refusal path.
- v3 (code-review SHOULD_FIX): fix `--help` line range (`2,32p`) with a test;
  pin the HOS repo's exact 11-context effective list in a frozen tuple.

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
3. Compare key logic paths against `scripts/framework/setup_branch_protection.sh`
4. Note any drift in a new version artifact (`setup_branch_protection.v1.md`)
