# Prompt Artifact — overseer.md

| Field | Value |
|---|---|
| **Generated file** | `.claude/agents/overseer.md` |
| **Description** | overseer posts verdict review objects and requests the CODEOWNERS human, scoped (#1657 PR 2 of 2) |
| **Date** | 2026-09-24 |
| **Model** | claude-opus-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

This change was **not** generated from a free-form prompt. It is the mechanical
application of an already-approved, fully-specified design: every replacement
string was authored in the design document and applied verbatim except where
noted under "Deviations" below.

The operative instruction to the authoring session was:

```
Apply PR 2 of 2 for issue #1657, per ADR-1657 §2 (ARCH-2, binding):
"PR 2 — 'Part 2 of 2: the overseer posts verdicts' (~7 files):
 .claude/agents/overseer.md, docs/FABERIX-ROLES.md, CLAUDE.md,
 bootstrap/overseer-cron-prompt.md, scripts/framework/require_overseer_approval.py
 (prose only), SCRIPTS-INDEX.md, tests/framework/test_overseer_verdict_artifact.py."

Sources of the exact text to apply, in precedence order:
  1. docs/v0.7.0/ADR-1657-overseer-review-objects.md  (BINDING; §3 conditions
     ARCH-1 … ARCH-11 govern wherever it differs from the design document)
  2. docs/v0.7.0/TECHNICAL-DESIGN-1657-overseer-review-objects.md
       §6.1–6.8  exact replacement wording for .claude/agents/overseer.md
       §7        edits E1/E2/E3 to docs/FABERIX-ROLES.md, plus the
                 require_overseer_approval.py stale-quote knock-on
       §8.3      the D1–D7 assertions for the new test file
       §9        what must NOT change (the "must not widen" pin)
       §10       ship-set, SCRIPTS-INDEX, CLAUDE.md row, cron-prompt line

Author the agent-definition edits directly in this session — do NOT delegate
them to the `coder` subagent (CLAUDE.md § "Agent-definition edits (HOS source
repo only)"). Delegate REVIEW normally.
```

## Constraints Specified

Governance-text change; no runtime/framework surface. The binding constraints
came from the ADR rather than from the prompt:

- **ARCH-5** — the verdict review has exactly ONE deduplication authority: the
  wrapper's own byte-identical-body-on-the-same-head guard. The #1215 precheck
  must NOT govern the verdict review.
- **ARCH-7** — the #761 `prior_overseer_decision` derivation must be left
  reading `/issues/{n}/comments` alone (still dead). Rewiring it would *revive*
  a dormant merge gate, adding a human gate to the LOW/MEDIUM non-protected
  path. Routed to #1839.
- **§9 claim 1 / "do not widen"** — the LOW/MEDIUM non-protected auto-merge path
  is byte-for-byte unchanged in behaviour: no reviewer is requested, no new gate,
  no new label. Requesting a human on every PR is the calibration failure
  `research/sessions/2026-08-04-controls-that-never-fire.md` records.
- **Trigger set is exactly two conditions** (above-ceiling/CRITICAL risk, or
  protected surface). Do not add a third.
- **A5 / ARCH-2** — `bootstrap/pr_review.sh` is NOT added to the consumer
  ship-set here; that is TD-1357 slice 6's, consistent with its two siblings.

What it must NOT do: introduce any new human gate; widen the reviewer-request
trigger set; rewire `prior_overseer_decision`; touch `protected_surfaces.txt`,
CODEOWNERS, or the tier matrix.

## Refinement History

**Deviations from the design's literal text, and why** (each disclosed to
`code-reviewer` and ruled correct):

1. The §6.3 replacement for the CRITICAL-tier bullet cited `:54` by line
   number. Replaced with "the NEVER list": this change's own insertions shift
   every line number in the file, and a stale citation is precisely the defect
   class #1657 is about.
2. The §6.3 CRITICAL bullet's step (2) read only "Post the verdict as
   `--event comment`", naming no wrapper — but D1 requires every disposition
   bullet to name `pr_review.sh submit-verdict`. Expanded to the full command.
3. Edits the design did not enumerate but which D1/D2 or plain consistency
   force: the PROPOSE_ONLY bullet (now posts a `comment` verdict), the step-6
   preamble, the v0.4.0-rules CRITICAL-tier line (was a direct
   `POST /pulls/{n}/requested_reviewers` carrying a hardcoded `ScottThurlow`),
   step 6b's "re-approve" line, the `detect_human_hold_directive` prose that
   follows the `human_reviewer=` call §6.4 mandates changing, and the
   "Executive summary" section's scope sentence.
4. `scripts/framework/require_overseer_approval.py` received two changes beyond
   §7's prose knock-on — a `spec is None or spec.loader is None` guard in
   `_load_sibling_module`, and a `black` reformat. Both were forced by blocking
   gates failing on **pre-existing** violations in that file (verified against
   the version on `main`); the gates scan whole files, not hunks.

**Review iterations:**

- v1 — first application of §6/§7. `code-reviewer` found two defects, both
  confirmed independently before fixing:
  - **MUST_FIX** — D7 was vacuous. The retired FABERIX quote is docstring-wrapped
    across two source lines (`do NOT\napprove`), so the literal single-line
    substring assertion never matched it and would have passed against a full
    revert. Fixed by collapsing whitespace before the check, then proved
    non-vacuous by running the assertion against `git show HEAD:` of the file.
  - **SHOULD_FIX** — two occurrences of the retired name "duplicate-comment
    precheck" survived the file-wide rename (`overseer.md:661`, `:691`). Both
    renamed; `:691` additionally gained the verdict's position in the SPEC-378
    halt-on-failure ordering.
- vFinal — 7/7 D-tests pass; 3661 passed / 15 skipped in the inner-loop suite.

## Human Review Notes

- **Reviewed by:** `code-reviewer` (agent); human review pending — `.claude/agents/**`,
  `CLAUDE.md`, `docs/FABERIX-ROLES.md` and `scripts/framework/**` are protected
  surfaces, so a CODEOWNERS human approves the merge.
- **Date reviewed:** 2026-09-24
- **Findings:** see "Refinement History" above — one MUST_FIX (vacuous D7), one
  SHOULD_FIX (two stale rename sites), both fixed. ARCH-5, ARCH-7 and the
  "must not widen" pin were each verified clean by the reviewer and
  independently re-checked.
- **Status:** APPROVED WITH CHANGES (agent review); awaiting human.

**The product decision this implements was made by the human, not by an agent.**
The 2026-09-14 ruling recorded in #1657 authorises exactly this change:
*"For a PR needing human approval, the overseer requests the CODEOWNERS human as
a required reviewer, and then approves if the change is ready for approval."*
This artifact implements that ruling; it does not extend it.

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `.claude/agents/overseer.md`
4. Note any drift in a new version artifact (`overseer.v1.md`)

Note the reproducibility target here is not a free-form generation: the
verifiable claim is that `.claude/agents/overseer.md` matches TD-1657 §6's
mandated replacement text, modulo the four disclosed deviations above.
`tests/framework/test_overseer_verdict_artifact.py` (D1–D7) is the mechanical
form of that check and runs in CI.
