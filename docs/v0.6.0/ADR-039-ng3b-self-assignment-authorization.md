# ADR-039 — NG3b release authorization: self-assignment replaces bot-assignment as the third signal

**Status:** ACCEPTED
**Date:** 2026-08-13
**Author:** architect (ruling captured verbatim below; transcribed by worker per this ADR's own §4)
**Issue:** #1347 (blocks #1338, the v0.6.0 release-cut request) · **Milestone:** v0.6.0 · **Risk tier: HIGH** (governs the release-cut gate itself)
**Consumers:** worker (`.claude/agents/worker.md` NG3b), overseer (`.claude/agents/overseer.md` bounce protocol), `scripts/automation/lib/merge_authority.py`, `bootstrap/edit_issue.sh`

---

## 0. Problem

GitHub does not permit assigning issues or pull requests to GitHub App/Bot identities on this repo. Confirmed 2026-08-13 via three independent checks against `hos-worker-hos[bot]`:

1. `gh api repos/{owner}/{repo}/assignees` (the assignable-users list) does not include it — only `ScottThurlow` appears.
2. `POST /repos/{owner}/{repo}/issues/{n}/assignees` with that login returns `403 Forbidden` (a genuine authorization rejection, not a 422 validation error).
3. GraphQL has no top-level `bot(login:)` query field, and `Repository.assignableUsers` is typed to return Users only, never Bots/Apps.

This is a hard GitHub platform constraint, not a missing permission or App configuration gap. The Release Authorization Protocol (NG3b, `.claude/agents/worker.md`) uses "assign this issue to `hos-worker-hos[bot]`" as one of three signals a human CODEOWNER must produce to authorize `cut_release.sh`, verified live via the GitHub Events API and never satisfiable by chat text. Since that action is categorically impossible, R1 condition 3 and R5's temporal/actor checks could never pass as written — this is why issue #1338 (v0.6.0's release-cut request) was stuck from 2026-08-12T20:46:30Z. `record_pr_bounce()` in `scripts/automation/lib/merge_authority.py` attempts the same impossible assignment on every PR bounce, failing silently (already wrapped in try/except, so non-blocking, but wasteful and produces a false `assigned_to` audit field).

---

## 1. Decision

**Self-assignment replaces bot-assignment as NG3b's third authorization signal**: the authorizing human CODEOWNER assigns the release-request issue to *themselves*, instead of to the bot. This preserves every anti-spoofing property the original design relied on — a real, timestamped, actor-attributed GitHub API event, not a chat message; tied to one identifiable human; verifiable live from the Events API; compatible with the existing "same actor for all three signals" invariant.

The naive port of this idea — literally swapping "assign the bot" for "assign yourself" everywhere the old text said "assign the bot" — is **not** what shipped. It is fail-open where the original was fail-safe (§2) and deadlocks the moment any validation-failure path runs (§2). Four additional, load-bearing changes make it safe. All four are binding, not optional refinements:

- **M1 — identity-triple check.** The authorizing `assigned` event must carry non-null `assignee.login` AND non-null `assigner.login`, with `assigner.login == assignee.login`, and any present `actor.login` must agree. Never substitute `actor.login` for a missing `assigner`. This makes the check correct regardless of which of GitHub's documented-vs-observed field semantics is true (§2), and makes a bot-performed assignment structurally unrepresentable as an authorization.
- **M2 — assignee-write ban on release-request issues.** The worker's only permitted write to the assignee field on such an issue is the M3 reset. No failure, escalation, or error path may assign any account there. Without this, the protocol deadlocks the first time a validation suite fails (the old failure paths reassigned `ScottThurlow`, which — combined with M1's absence — is exactly the forgery path M1 closes; keeping the failure-path reassignment while adding M1 would just make M1's protection load-bearing on every validator run instead of only at authorization time, for no benefit).
- **M3 — deterministic anchor reset.** R4 clears all assignees on the issue *before* posting the results comment, so "the issue is unassigned" is true when the human reads the instructions, and so a genuine self-assignment necessarily produces a fresh `assigned` event postdating the comment. Without this, a human already self-assigned from a prior failed attempt produces no new event (GitHub does not emit `assigned` for a redundant assignment) and the wait is silent and permanent — reproducing the exact failure class this ADR exists to fix.
- **M4 — AWAITING vs VIOLATION split.** "No qualifying signal yet" (human hasn't finished acting) and "a disqualified signal exists" (spoofing attempt or misconfiguration) are different outcomes. Under bot-assignment, "assigned to a human" was itself disqualifying, so a blanket "any failure fires `ng3b-violation-attempt`" rule was harmless. Under self-assignment, "assigned to a human, no event yet" is the *routine, expected, in-progress* state, and firing a violation event on every such read would make the audit log noise, not signal. AWAITING conditions fire no event; only a disqualified signal fires one. A one-time diagnostic comment (`<!-- hos-ng3b-awaiting -->`) is posted the first time a request is found AWAITING, naming which of the three signals is outstanding — because a silently-unsatisfiable NG3b condition already cost this project a release cycle (#1338), and a stalled gate must say what it is waiting for.

---

## 2. Why the naive port is unsafe — the reasoning, not just the rule

**(a) The worker itself can produce the "authorized" assignee state.** Under the old design, five NG3b failure paths (R3, R4 dirty-tree, R6 ×3) ran `edit_issue.sh --assignee ScottThurlow` — a state no agent could otherwise create, since only the bot could be a *worker-assigned* value and bots can't be assigned at all. "Assigned to the bot" was therefore a state exactly one path (the human's authorizing action) could ever produce. Under self-assignment, "assigned to a human CODEOWNER" is a state the worker creates *routinely*, as a side effect of ordinary error handling. Combined with this repo's own prior finding that GitHub's Issue Events API can carry `actor.login` as the *assignee* rather than the performer of an `assigned` event (`research/findings/api-field-shape-verification.md`, #348, 2026-06-16 — a live-response contradiction of GitHub's documented field semantics, not a hypothetical), an implementation reading only `actor.login` would read a worker-performed assignment as `ScottThurlow` and the three-signal check would pass. The old design failed **closed** under that same field-name ambiguity (assignee was the bot → in `BOT_ACCOUNTS` → reject regardless of which field meant what). The naive port fails **open** — a genuine new privilege-escalation path, closed by M1 (which is semantics-agnostic: it requires whichever fields are present to agree, so it is correct under either reading of GitHub's API) combined with M2 (which removes the worker's ability to write the field on these issues at all, so there is nothing for M1 to be tricked by).

**(b) The common path silently deadlocks without M3.** GitHub emits no `assigned` event for a redundant assignment. Any failure path that assigns a human (pre-M2 design) or any prior self-assignment attempt (post-M2 design, if the anchor isn't reset) leaves the issue already assigned by the time R4 posts — so "assign yourself" is a no-op, produces no event, the freshness condition never holds, and the worker waits forever while the human believes they already acted. This is the identical failure class as #1347 itself, re-created one layer down. M3 (reset-before-post) and M2 (no other path may write the field) together are what make the freshness condition satisfiable on every request, not just the first.

**Residual risk, accepted.** Self-assigning is a lower-ceremony, more common gesture ("I'll take this") than assigning a bot was, so it is a slightly weaker "I am authorizing this" signal in isolation. This residual is bounded and accepted because: (i) the semantic intent is carried by `release-authorized`, not the assignment — the assignment is the freshness/accountability anchor, not the approval itself; (ii) the three-signal same-actor requirement still applies in full; (iii) the freshness condition (event must postdate the results comment) rules out a stale pre-emptive self-assign; (iv) M3 guarantees the anchor reads as empty at the moment the human reads the instructions. Enforcing a strict signal *order* (self-assign must be the temporally last of the three) was considered and rejected — it would close the last sliver of this residual but reintroduce a silent-deadlock class (self-assign-first produces no event to re-trigger on), which is the bug this ADR exists to fix.

**Side effect, not a design goal but worth recording:** the accountable human is now the visible assignee of record on the release issue in every GitHub listing. The bot never was accountable for the release in that sense; the old assignee semantics were arguably wrong on their own terms even before the platform-constraint bug surfaced.

---

## 3. Process-gap ruling: who edits `.claude/agents/*.md` in this repo

A coder subagent attempting a draft of this fix reported it is blocked by its own CORE instruction (`.claude/agents/coder.md` line 83): *"Do not write to your own agent definition file or any other agent's definition file (`.claude/agents/*.md`). These are HOS-managed; edits go through the installer."*

**Ruling: the top-level worker/human-proxy session edits `.claude/agents/*.md` directly in this repo. `coder` is never dispatched for those files, and `coder.md`'s CORE prohibition is not weakened or carved out.**

Reasoning:

1. This is the established, repeated pattern, not an exception: `git log --oneline -- .claude/agents/worker.md .claude/agents/overseer.md` shows direct `hos-worker-hos[bot]` authorship across many commits (e.g. 87337f31, 4450db47, d5a494f6, and others).
2. The actual anti-tampering control is the protected-surface gate, not which agent typed the edit. `.claude/agents/**` is the first entry in `scripts/framework/protected_surfaces.txt`; any PR touching it requires human approval and can never be bot-merged, and `.github/CODEOWNERS` is generated from that same list. This property holds regardless of whether `worker` or `coder` authored the diff.
3. `coder.md`'s prohibition is defence-in-depth for *consumer* projects, where the installed copies of these files carry no such protected-surface gate. Adding a conditional carve-out ("...unless this is the HOS source repo") to a CORE rule that ships to every consumer would be a self-assessed exemption a consumer's coder could reason itself into applying — the same failure class as #556. CORE stays verbatim.
4. The clarification instead lives in this repo's own `CLAUDE.md` (§"Working in this repo"), which is HOS-source-specific, never ships to consumers, and is itself a protected surface.

Practical split applied to this fix: the worker session authored all `.claude/agents/*.md`, `CLAUDE.md`, `contract/OVERSIGHT-CONTRACT.md`, and `docs/MACHINE-ACCOUNTS-SETUP.md` changes directly; `coder` was dispatched only for `scripts/automation/lib/merge_authority.py`, `bootstrap/edit_issue.sh`, and their tests — ordinary application/tooling code, ordinary rules.

---

## 4. Implementation record

Implemented in the same PR as this ADR (issue #1347):

| File | Change |
|---|---|
| `.claude/agents/worker.md` | R1 condition 3 → issue state `open` (assignee removed as a trigger condition); new R0 assignee-write ban (M2); R4 idempotency keyed on `Release candidate SHA`, new step 0 anchor reset (M3), steps 6–7 and the "How to authorize this release" block reworded for self-assignment; R5 replaced in full (current-state conditions, M1 identity-triple check on the authorizing event, three-signal actor check, M4 AWAITING/VIOLATION split with one-time diagnostic comment); R3/R4/R6 failure paths no longer write the assignee field; `ng3b-violation-attempt` `failed_check` enum and example updated; "Re-entry after a bounce" section and the generic `needs-human` "How to authorize" footer no longer reference bot-assignment; script-inventory table documents the new `edit_issue.sh --set-assignee` flag |
| `.claude/agents/overseer.md` | Bounce-protocol descriptions (`record_pr_bounce()` mentions, the finalize-step list, the canonical-labels table, the `edit_issue.sh` inventory row) no longer describe an assign-to-bot step |
| `CLAUDE.md` | New clause in "Working in this repo" recording §3 |
| `contract/OVERSIGHT-CONTRACT.md` | `pr-bounced` description and `assigned_to` example updated to reflect the field is always `null` (retained for schema stability) |
| `docs/MACHINE-ACCOUNTS-SETUP.md` | `release-authorized` label description and surrounding prose updated to self-assignment language |
| `scripts/automation/lib/merge_authority.py` | `record_pr_bounce()` — removed the doomed `/assignees` POST call, its `try/except`, and the `assignee` parameter; `assigned_to` is now always `None` in the emitted event |
| `bootstrap/edit_issue.sh` | New `--set-assignee <user\|none>` mode (`PATCH` with a replacing `assignees` array) alongside the existing add-only `--assignee`; required by R4 step 0 |
| `tests/automation/test_bounce_gate.py`, `tests/automation/test_edit_issue.py` | Updated/added to match |

**Verification obligation — blocking on declaring #1338 unblocked, not on merging this PR.** Before relying on this protocol for an actual release cut, the implementation must capture a live `assigned` event payload from a real human self-assignment on this repo and confirm `actor`/`assignee`/`assigner` resolve as R5 conditions 4–6 expect, and append the finding to `research/findings/api-field-shape-verification.md`. A mocked test cannot catch a wrong field name — it will faithfully mock the wrong field. That is exactly how this repo reached #1347's bug in the first place. This will happen naturally the first time a human authorizes a release under the new protocol (e.g. re-authorizing #1338); no separate drill is required, but the finding must be recorded when it does.

**Affected sign-offs.** Stand unchanged: NG3b's R0 identity guard, R1.5 creator check, R2 tier matrix, R4 HEAD-SHA binding, R6 command-precision check — none of these are touched by this ADR. Also stand: prior approvals of the bounce mechanism's finalize *behavior* (posting the comment, applying `needs-ai`, converting to draft) — the assign call never succeeded, so no reviewed behavior actually changes there, only a dead call and a false audit field are removed. Orphaned by this ADR, requiring re-review against it if revisited: the original R1/R4/R5 assignment-signal design.

**On #1338 specifically:** at the time this ADR was written, #1338 carried `release-request`, `release-authorized`, and `needs-human`, with no assignees. Under the revised R5 it reads AWAITING on two counts (`needs-human` still present; no self-assignment event). Once this fix lands, the next worker cycle re-runs R2–R4 for the current HEAD and posts a fresh authorization request; #1338 does not need to be reset or recreated.
