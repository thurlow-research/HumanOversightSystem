# Prompt Artifact — check_role_writability.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/framework/check_role_writability.py` |
| **Description** | Static check: every risk-assessor-emittable role is writable by its mapped agent (#2276) |
| **Date** | 2026-11-08 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Implement issue #2276 part C (human ruling "A + C"): a deterministic static check
that every role the risk-assessor can emit is writable by its mapped agent.

Background: the risk-assessor writes role keys to required-reviewers.md; the
oversight-evaluator requires a register entry per role and cannot waive one.
The risk-assessor required `architect` while architect.md forbade any register
entry, so every ADR step failed Phase 1. Part A (fa4042b05) added role
`architecture: architect` to the contract section 5 and step-manifest template
role_mappings, scoped the architect.md prohibition, and named the roles in
risk-assessor.md Phase 6.

Build scripts/framework/check_role_writability.py (stdlib only; sibling scripts
do not require PyYAML for this). Emittable roles = every key in the contract
and template role_mappings blocks (template commented-out `# key: agent`
included) plus every backticked key after "adds" on bullets in the risk-assessor
Phase 6 section only. Findings: (1) emitted role with no mapping; (2) contract
and template disagree on the agent; (3) mapped agent file missing; (4) mapped
agent file has an unscoped register-write prohibition (module-level regex
constant; a same-line "only when" / "except when" / "unless" scopes it).
CLI: python3 -m scripts.framework.check_role_writability [--repo-root PATH]
[--quiet]; exit 0 clean, 1 findings, 2 missing required file or empty
role_mappings (fail closed). Wire into check_agents_static.sh as section
10, add tests under tests/framework/ using tmp_path only, and run regen_all.sh.
Do not edit .claude/agents/*.md, contract/**, or docs/AGENTS.md.
```

## Constraints Specified

- Stdlib only; python3, run from repo root (CI: bash check_agents_static.sh).
- Fail closed: an empty role set or missing role_mappings block exits 2.
- Must not edit agent definitions, contract, or docs/AGENTS.md.
- Real architect.md (scoped prohibition) must pass; the pre-fix text must trip.

## Refinement History

v1: prohibition regex allowed any text between the negation and "write", which
false-positived on every reviewer's "do not attempt a 6th round ... write a
Status: ESCALATED register entry" line (10 files).
v2: the negation must directly govern "write" (at most two words between) and
"register entr" must follow in the same sentence. Real tree is clean.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Round 2 (code-review round-1 fixes)

- Section 10 of check_agents_static.sh is gated on the checker file existing (legacy install.sh --source copies the script without it): warn and skip when absent; a missing contract with the checker present stays a FAIL.
- Strip markdown emphasis before SCOPE_RE; widen the prohibition regex (must/may/shall not, cannot, can't, writes/writing); document single-line matching.
- Commented mapping lines count only as `# <role>: <agent>` + EOL or `#` comment.
- Cross-check emitted roles and role_mappings keys against the contract section 3 `**Roles**` table (missing role FAIL, missing table exit 2).
- Tests added for each, plus section-10 skip and failing paths through check_agents_static.sh.

---

## Round 3 (second-review findings)

- PROHIBITION_RE gains a post-verbal alternation (`writes?|writing` + `no` ... `register entr`).
- Scope words must be in the same sentence as the prohibition (split on `[.;?!]` followed by whitespace, so dotted paths do not split).
- Tests: post-verbal, cross-sentence scope, same-sentence scope, dotted path, and the real architect.md line (matches the prohibition, suppressed only by same-sentence "Unless").

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `scripts/framework/check_role_writability.py`
4. Note any drift in a new version artifact (`check_role_writability.v1.md`)
