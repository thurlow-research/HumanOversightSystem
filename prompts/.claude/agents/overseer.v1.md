# Prompt Artifact — overseer.md

| Field | Value |
|---|---|
| **Generated file** | `.claude/agents/overseer.md` |
| **Description** | Record the #1839 ruling: the #761 `prior_overseer_decision` guard stays dead (settled, not pending) |
| **Date** | 2026-10-11 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Autonomous worker cycle (bin/hos-cron --role worker). The selector's first
candidates were #1944 (reserved for interactive sessions) and #1816 (on human
hold pending #1936). The next candidate was #1839, which carries a human ruling
(2026-10-02) in its thread:

```
Q1: Do not revive. [...] Leave the guard dead.
Q2: Moot given Q1.
Per this issue's own acceptance criteria: update the in-file note added by
#1657 (ARCH-7) to say this is now a settled decision, not a pending one.
```

The matching acceptance criterion: "If the guard stays dead, the in-file note
added by #1657 (ARCH-7) is updated to say that is now a settled decision rather
than a pending one."

Authored directly by the top-level worker session (CLAUDE.md § "Agent-definition
edits (HOS source repo only)") — not delegated to `coder`.

## Constraints Specified

- Text-only: the guard stays dead; no change to `merge_authority.py` or to the
  `prior_overseer_decision` derivation instructions.
- The note must say the decision is settled, not pending.

## Design choices made by the authoring session (not in the issue text)

1. **Scope** — only the ARCH-7 "knowingly NOT wired" paragraph is edited. The
   derivation instructions below it and the `**Decision: HUMAN_REQUIRED**`
   marker paragraph (which says the #761 guard scans for the marker) are left
   alone. Both are still literally accurate: the derivation still runs and the
   guard still exists in `merge_authority.py`. It just never matches.
2. **Revival path** — the note says reviving the guard needs a new human ruling
   that supersedes #1839. That replaces "until that is answered", which no
   longer has an answer to wait for.
3. **Rationale** — one clause from the ruling (rubber-stamping degradation on
   the highest-volume, lowest-risk PR class) is quoted, so a reader does not
   have to open #1839 to see why.
4. **No new test** — #1839's acceptance criteria require a pinning test only on
   the revival path.

## Refinement iterations

1 — initial authoring.
2 — code-review round 1 (CHANGES_REQUESTED, 1 SHOULD_FIX + 2 NITs). No text
    change:
    - SHOULD_FIX "unsourced rationale clause": a false positive. The
      reviewer's prompt quoted the ruling in abbreviated form. The full #1839
      ruling says: "a human-approval requirement that fires on the
      highest-volume, lowest-risk PR class is exactly the
      rubber-stamping-degradation pattern this needs to avoid". The clause
      paraphrases that sentence.
    - NIT "new human ruling supersedes #1839": kept (design choice 2).
    - NIT "pointer from the derivation instructions": declined (design
      choice 1, scope).
