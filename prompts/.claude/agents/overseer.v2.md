# Prompt Artifact — overseer.md

| Field | Value |
|---|---|
| **Generated file** | `.claude/agents/overseer.md` |
| **Description** | §3b applicability precondition: not evaluable when step unconfigured (#1652) |
| **Date** | 2026-10-19 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (validated by risk-assessor; declared MEDIUM) |
| **Human review status** | ⬜ Pending |

---

## Prompt

The top-level autonomous worker session authored the edit directly. It did not go
through `coder`, because CLAUDE.md says agent-definition edits in the HOS source repo
are authored at the top level. The specification it worked from was the human ruling
on #1652 (2026-09-15):

```
§3b's fail-close freshness check does not apply to this repo's own
self-hosted PRs while step-manifest step 1 remains unconfigured here. ...
`overseer.md` §3b should say this explicitly — mirror how `register`'s
`gate_evaluable: false` already handles "not configured for this step,"
rather than leaving the literal algorithm to fail-close on every PR once its
reference artifact ages past whatever commit last refreshed it. ...
If this repo's self-hosted flow later gets its own step-manifest step 1
configuration, this exemption should be revisited then — record that
condition in the same place so a future reader knows why the check is
currently silent, not forgotten.
```

## Constraints Specified

- Key the exemption on `merge_authority_cli register --app overseer --step <N>` →
  `gate_evaluable` (the existing primitive), not a new mechanism.
- Record the revisit condition in §3b itself.
- Record the skip as NOT EVALUABLE in the executive summary, never as a pass; all
  other gates still apply.
- Must not fail open for consumer projects (overseer.md ships to them).

## Refinement History

- v1 (cf1596bd2): precondition + Why/Revisit paragraph.
- pm-agent A1 (f13339e96): "4a onward" → "step 4 onward".
- architect AR-1/AR-2 (6eb72858a): a failed register call means fail closed. A
  manifest that is present but unresolved (malformed, block-style list, or no entry
  for step N) still skips §3b but routes HUMAN_REQUIRED and never auto-merges. This
  closes the consumer-side fail-open, where §4a was already silent on the same empty
  signoff list.
- risk-assessor (validated HIGH) open gap 2, plus architect AR-6/AR-7: probe both the
  PR head and the default branch after a fetch, and count a failed fetch or ref as
  present. The cases are restructured into a list so each one has a single summary
  record.
- code-reviewer F1/F2: `git cat-file -e` exits 128 for both a bad ref and a missing
  path. Both refs are now confirmed with `git rev-parse --verify` before a probe can
  mean "missing". `gate_evaluable` must be the literal boolean `false` for a skip.

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
2. Paste the prompt above exactly as written
3. Compare key logic paths against `.claude/agents/overseer.md`
4. Note any drift in a new version artifact (`overseer.v3.md`)
