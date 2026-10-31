# Prompt Artifact — ADR-2209-overseer-rejections-to-worker.md

| Field | Value |
|---|---|
| **Generated file** | `docs/v0.7.0/ADR-2209-overseer-rejections-to-worker.md` |
| **Description** | ADR for #2209 overseer rejections routed to worker (architect) |
| **Date** | 2026-10-30 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | HIGH (diff_size tier floor: 489 changed lines > 400) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Dispatched by the autonomous worker to the `architect` subagent (exact text except the absolute clone path, replaced with `<Worker clone root>` for the portability gate):

```
Write the ADR for HOS issue #2209 at `docs/v0.7.0/ADR-2209-overseer-rejections-to-worker.md` in <Worker clone root> (branch `worker-2209-overseer-rejections-to-worker-261030163501-565392`; do NOT switch branches, do NOT commit, do NOT file issues or change labels). Follow the shape of a recent ADR such as `docs/v0.7.0/ADR-2101-github-native-human-authorization.md`.

Input: the requirements just written and committed at `docs/v0.7.0/REQUIREMENTS-2209-overseer-rejections-to-worker.md` (REQ-1..REQ-14, ESC-1..ESC-3). Read it first. Ground every decision in current code: `.claude/agents/overseer.md` (steps 4a/4c, step 6 HUMAN_REQUIRED, expected-human-action enum, §8.2), `scripts/automation/lib/merge_authority.py` (`bounce_count`, `record_pr_bounce`, `check_required_content_checks`, `decide_merge_authority`), `scripts/automation/merge_authority_cli.py`, `bootstrap/overseer-cron-prompt.md`, `bootstrap/lib/comment_format_check.sh`, `.claude/agents/worker.md` §"Re-entry after a bounce".

Decide the architecture-level questions the requirements leave to you, at minimum:
1. Where the "worker-fixable finding vs. decision needed" classification lives — prompt judgment in overseer.md vs. a deterministic helper in merge_authority.py — and the boundary between them (prefer deterministic code for routing, counters and dedup; LLM only for the merits finding itself).
2. How a worker dispute is expressed and detected (structured, machine-detectable marker tied to a finding id) and how the overseer records "upheld".
3. Bounce-budget identity across the worker's re-entry PR (bounce → new PR): what the `cid` key is so the cap is reachable, and same-head idempotency.
4. Bounce comment content: per-finding ids and the `### Specific failures` section the worker re-entry expects; new reason_category value(s) for merits findings.
5. Ordering in the overseer step list (extend #1580's 4c ordering so merits bounces precede the protected-surface gate) without weakening CODEOWNER final approval (REQ-10).
6. Slicing: propose a small number of independently landable slices (S1, S2, ...) with files per slice, each ≤15 files. Note that #2174 (unlanded local branch `worker-2174-overseer-interim-signoff-261030062001-12459`) edits overseer.md, overseer-cron-prompt.md, pr_review.sh, pr_review_cli.py — order slices so the code slices that touch those files land after #2174, or keep their edits disjoint.

Do not re-decide what the human already ruled (no exemptions by tier/surface/class). Where the requirements' ESC defaults are architecturally sound, say so; list any ARCH-ESC items that truly need the human. Keep it concise (aim under ~250 lines). Report the path and a short summary of decisions + slices.
```

## Constraints Specified

- Must not re-decide the human's 2026-10-29 ruling (no exemption by tier, surface, CODEOWNERS or finding class).
- Must preserve CODEOWNER final approval of a clean protected-surface PR (REQ-10).
- Must not commit, switch branches, file issues or change labels.
- Slices ≤15 files each; sequence around the unlanded #2174 branch.

## Refinement History

v1: initial ADR (above prompt).
v2: revised after code review round 1 (`.claudetmp/signoffs/step2209-register.md`
§ code-review): MUST_FIX-1 (no resolution path after ESCALATE → new AD-5a,
human act on the head after the escalation resolves it), SHOULD_FIX-1
(`--ready-pr` removes `needs-ai`), SHOULD_FIX-2 (S1 legacy bounce-comment
rendering stated), SHOULD_FIX-3 (REQ-2 qualified by ESC-3), nits, plus the
risk-assessor's withdraw-visibility and branch-derived cid items (R-4).
v3: revised after code review round 2 (APPROVED with SHOULD_FIX-A/B/C) and
the risk-assessor's re-assessment of AD-5a: suppression is head-scoped;
cid binding is a hard, server-side-checked S1 requirement; human override
cannot clear code-collected findings; AD-5a reuses step 6's approval check;
the `route` CLI fetches its own inputs and fails closed; canonical finding
keys; code-rendered withdraw visibility; crash-safe resolution; decision
approvals must name an option.
v4: revised after code review round 3 (CHANGES_REQUESTED): AD-3 lineage
also accepts the bounced PR's own number; withdraw/override carry forward
only when the finding's file blob is identical between heads (code-checked,
fail-closed to an annotated re-raise); no second bounce on one head (HOLD);
transient vs deterministic merge-failure classification.
v5: revised after cross-vendor second review (codex HIGH CWE-863) and
security review round 1 (MUST_FIX prompt injection via dispute reason):
automatic carry-forward removed (fresh `--carry` ruling per head, no
bounce); dispute reason treated as untrusted data with evidence-cited
withdraws and a code-enforced veto window; latest-act-wins review scan on
GitHub timestamps; CODEOWNERS read from base ref; `route` exit contract +
`merge-guard`; capped refusal audits; status PROPOSED.
v6: revised after code review round 5 (liveness MUST_FIX) and the delta
second review (codex HIGH: dismissed approval resurrects an older one):
missing rulings default after one cycle (carry → reinstate/bounce,
unruled dispute → uphold/escalate); rule 2b narrowed so option (a) reaches
the veto window; latest act chosen before dismissal is evaluated
(dismissal = revocation → HOLD); CODEOWNERS parser kept in
merge_authority.py (S1 = 14 files); evidence format reconciled.
v7: revised after security review round 2 (MUST_FIX: worker push defeats
the veto window; rule 2a PROCEED without re-evaluation): sticky holds per
cid until a human act on the current head; non-re-raised withdrawn keys
listed and windowed; rule 2a removed, merge-guard re-runs code findings,
checks and holds live; evidence bound to the finding's own path/check;
residual R-6; ARCH-ESC-2 (security-class withdraw rule) for the human.
v8: revised after code review round 7 (MUST_FIX: rule 4(d) unreachable
behind 2b) plus security round-3 and risk-assessor follow-ups: one flat
8-rule precedence with the veto check top-level; same-head NOOP compares
(class, path) not LLM wording (residual R-7); release-hold pinned to the
resolved reviewer; merge-guard defined for LEGACY; check: evidence limited
to check findings; issue cid no longer depends on worker-written lineage.
v9: revised after the delta second review (codex HIGH: branch-name cid lets
held work escape a sticky hold) and code review round 8 (MUST_FIX: issue
cid contaminates sequential slices): holds and pending escalations follow
the changed-path set (`path_blocks`, GitHub PR files API); budget,
withdrawals and rulings count per issue epoch reset by non-worker merge or
close; veto window delays only PROCEED; residual R-8.
v10: revised after the delta second review (codex HIGH x2: hold paths read
from a mutable endpoint; epoch reset erases sibling obligations) and code
review round 9 (MUST_FIX: final-approval waits counted as pending
escalations): hold/escalation paths from immutable compare of the
overseer-recorded head; epoch resets only budget and withdrawn-set for
later-opened PRs; pending escalation = AD-5 ESCALATE only; blocked-PR note;
PATH_BLOCK_EXCLUDE for shared generated files.
v11: revised after the delta second review (codex HIGH x2: compare-failure
fallback escapes cross-issue; CODEOWNERS exclusion) and code review round 10
SHOULD_FIXes: paths[] persisted in each per-head event at write time; unknown
scope blocks all worker merges; authorization-policy files never excluded;
hold scope = union of recorded heads; merge-guard posts the block note;
residual R-9.
v12: revised after the delta second review (codex HIGH: push-to-event gap
lets a hold on an unrecorded head miss its paths) and security round 4
SHOULD_FIXes: `head-observed` paths[] on first sight of every head; a hold
is scoped only if the held head (from the PR timeline) is recorded, else
global unknown-scope block; complete paths incl. renames/removals,
truncation fails closed; residual R-10; release only on the originally
held PR; path normalisation.

The worker independently verified the ADR's central
finding (`derive_cid` has no production caller, so the overseer's `cid` is
unspecified) by grep before committing. The claim about the overseer clone's
audit-log contents was not verifiable from the Worker clone.

## Human Review Notes

<!-- After human review, record findings here. -->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above exactly as written
3. Compare key decisions (AD-1..AD-6, slices) against `docs/v0.7.0/ADR-2209-overseer-rejections-to-worker.md`
4. Note any drift in a new version artifact (`ADR-2209-overseer-rejections-to-worker.v1.md`)
