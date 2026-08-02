# Requirements Spec — Issue #967: Worker Branch Ownership (PRs only for branches the worker created)

**Document type:** Requirements specification
**Status:** Draft — for architect review, then technical-design
**Issue:** #967
**Milestone:** v0.6.0 (as labelled on the issue — see §11, OQ-6)
**Risk tier (declared for downstream routing):** **HIGH** — governance-critical autonomous-worker surface (same class as the #556/#558 pipeline-discipline rules)
**Related:** #556, #558 (pipeline discipline), #317 (worker pre-PR gate), #1053/#1059/#1089 (clone separation policy), #1162 (stale-base guard in `submit_pr.sh`)
**Evidence:** thurlow-research/CondoParkShare PR #188, issue #187
**Date:** 2026-08-02
**Author:** pm-agent

---

## 1. Problem Statement

A human-driven interactive orchestration session and the autonomous worker cron were
operating on the **same git checkout**. The orchestrated `coder` committed an in-progress
fix to a branch for a `needs-ai` issue — **before** the `code-reviewer` had approved it.
The worker cron then fired, saw a commit on a branch associated with a `needs-ai` issue,
concluded the work was finished, and **opened a PR from the unreviewed commit**. That
commit still carried a finding the `code-reviewer` subsequently flagged as BLOCKING. The
orchestrator had to force-push the reviewer-approved commit over the worker's PR head to
recover.

The defect is not "the worker lacked a completion signal." The defect is that the worker
**inferred** that a branch was a finished, PR-able work product from the fact that *a
commit existed on it*. Under that inference, any other session's in-flight branch is a
candidate for auto-PR, and author≠reviewer independence can be bypassed by accident.

The inference is not merely prose. It is codified: `scripts/automation/lib/correlation.py`
returns `ResumeState.BRANCH_EXISTS` when a branch matching the cid-derived name is present,
and `COLD_START_TABLE[BRANCH_EXISTS]` reads *"Branch exists — open PR (idempotent; branch
already created)."* That is the mechanical form of exactly the inference this spec removes.

---

## 2. Decision (given — not open for re-litigation)

The human decision of 2026-08-02 (issue #967 comment thread) is **authoritative and
supersedes the three options in the issue body**. It is reproduced here as a given, not as
a proposal. Neither the architect, technical-design, nor any reviewer should re-open the
ownership-vs-lock-vs-ready-signal question.

**The model is ordinary git flow:**

> Create branch → work → submit PR → branch deleted on merge.
> **When the worker finishes the work, the worker submits the PR.**

**The rule is ownership, not inference:**

1. The worker opens PRs **only for branches it created in its own work cycle**.
2. A branch created by an interactive/orchestrated session is **never** the cron worker's
   to submit — regardless of what commits appear on it or which issue it references.
3. *"A commit exists on a `needs-ai` branch"* stops being evidence of anything. That
   inference is **deleted, not refined** — not wrapped in an additional guard, not
   demoted to a heuristic, not retained behind a flag.
4. **Ownership is recorded, not inferred.** There must exist a durable artifact that
   *states* which branch this worker cycle created. Nothing derived from branch names,
   commit presence, commit authorship, issue labels, or checkout state may substitute
   for that record.
5. **Branch lifecycle:** one branch per unit of work; **branch deleted on merge.** A
   merged-but-undeleted branch is exactly the stale artifact a scanning worker can
   rediscover and act on.

**Relationship to worktree isolation:** dedicated worktrees for interactive work remain
worthwhile as defence in depth, but are **no longer the primary fix** and are out of scope
here (§6). Ownership lands first; worktree isolation is separate hardening.

---

## 3. Scope

### In scope

- A **branch-ownership record**: what is written, where, by what, and when (§5, R1–R3).
- **Enforcement** of that record at the PR-opening chokepoint, `bootstrap/submit_pr.sh`
  (§5, R4–R6).
- **Removal** of the existing completion-by-inference logic from the worker's autonomous
  path, including its codified form in `correlation.py` / `COLD_START_TABLE` and its prose
  form in `.claude/agents/worker.md` and `bootstrap/worker-cron-prompt.md` (§5, R7).
- An **audit event** on refusal (§5, R9).
- A **regression test** reproducing the #967 scenario (§7, T1).
- Governance-doc updates so the recorded-ownership rule is stated where the worker's
  behaviour is defined (§5, R10).

### Out of scope

- **`--app human` and its `--confirmed` exception path.** The human-proxy direct-PR path is
  already governed separately (`docs/AGENT-IDENTITY.md`, per-instance human authorization)
  and is not implicated in this defect. It **must not** acquire an ownership requirement as
  a side effect of this change. Its behaviour is unchanged.
- **`--app overseer`.** The overseer never creates branches and never opens PRs; it was
  verified in the issue as correctly *not* tree-scoped. Its behaviour is unchanged.
- **Worktree / clone isolation for interactive sessions** (separate hardening; see §2).
- **The policy/docs half of the earlier 2026-07-30 comment** (mandating three-clone
  separation), which is blocked on #1053/#1059/#1089.
- **Register/sign-off verification as a PR precondition.** The 2026-07-30 "verify
  code-reviewer sign-off exists for the commit" backstop is superseded by the 2026-08-02
  ownership decision and is not specified here. Pre-PR readiness remains #317's concern.
- Any change to *which* issues the worker selects, or to triage, claim, or cid derivation
  semantics beyond the removal required by R7.

---

## 4. Definitions

| Term | Meaning |
|---|---|
| **Work cycle** | One autonomous worker invocation: a single `bin/hos-cron --role worker` run and the Claude session it launches, from launch to exit. |
| **Cycle identity** | An identifier that uniquely names one work cycle. **No such identifier exists today** — `bin/hos-cron` mints nothing of the kind. It is new. |
| **Owned branch** | A local branch created by the current work cycle, for which a valid ownership record (R1) exists. |
| **Foreign branch** | Any branch that is not an owned branch — including branches created by an interactive/human session, by another agent, by a prior worker cycle, or by a human at the terminal. The default classification: anything not positively recorded as owned is foreign. |
| **Ownership record** | The durable artifact asserting "work cycle *C* created branch *B*" (R1–R3). |
| **PR-opening chokepoint** | `bootstrap/submit_pr.sh` — per CLAUDE.md, the only sanctioned path to push a branch and open a PR under a bot identity. Hand-composed `gh pr create` is already forbidden. |

---

## 5. Functional Requirements

### R1 — A branch-creation step writes an ownership record

Branch creation by the autonomous worker MUST go through a step that, as part of creating
the branch, **writes a durable ownership record**. Creating a branch and recording
ownership are one operation; a path that creates a branch without producing a record MUST
NOT exist in the worker's autonomous flow.

Today the worker creates branches by running `git checkout -b <name>` as a raw shell
command guided by prose in `.claude/agents/worker.md` ("always create a dedicated working
branch"). There is no committed script for it. Satisfying R1 therefore requires a
branch-creation seam that did not previously exist; technical-design owns its shape.

### R2 — Record contents and keying

The ownership record MUST be:

- **Keyed by branch name.** Given a branch name, a checker can determine in one lookup
  whether a valid record exists for it.
- **Scoped to a specific work cycle.** The record MUST identify *which* cycle created the
  branch (§4, cycle identity), not merely that "some worker" did.
- **Scoped to the worker role.** A record MUST NOT be producible by an interactive/human
  session or by the overseer as a by-product of normal operation.
- **Timestamped**, so staleness is decidable (R3).
- **Durable** for at least the lifetime of the work cycle, and machine-local — see R8.

The record's serialization format, storage location, and the mechanism for minting cycle
identity are **technical-design's** to choose within these constraints.

### R3 — Validity: what counts as a valid record

A record is **valid for opening a PR on branch B** only if all hold:

1. It exists and is keyed to exactly `B` (no prefix, glob, or pattern matching).
2. Its cycle identity equals the cycle identity of the **currently running** worker cycle.
3. Its role scope is `worker`.

Explicitly, and by construction, a record is **never** valid when:

- it was written by an interactive, orchestrated, or human-proxy session; or
- it was written by a **prior or stale** worker cycle (see §11, OQ-1 — the fail-closed
  reading governs until the human resolves it); or
- it is absent, unreadable, malformed, or keyed to a different branch.

### R4 — `submit_pr.sh --app worker` refuses without a valid record

`bootstrap/submit_pr.sh` invoked with `--app worker` MUST refuse to push and MUST refuse to
open a PR when no record valid per R3 exists for the resolved `--head` branch. The refusal
MUST occur **before** any token is minted and before any push, and MUST exit non-zero with a
message that names the branch and states that ownership was not recorded.

The check joins the existing `--head` validation sequence (local-ref existence, stale-base
check, #1162/#1166). Its ordering relative to those checks is technical-design's call; its
position **before** token mint and push is not.

### R5 — Fail-closed

Any inability to evaluate the ownership record — missing store, unreadable record,
unparseable content, absent cycle identity, ambiguous match — MUST be treated as **"no
valid record"** and therefore as refusal. There MUST be no override flag, no environment
escape hatch, and no "open anyway" path for `--app worker`. This mirrors the framework's
existing posture (#317 REQ-W-16: the gate is not a judgment call).

### R6 — Enforcement scope: worker only

- `--app worker`: R4/R5 apply.
- `--app human`: unchanged. The existing `--confirmed` requirement remains the sole
  gate on that path; no ownership record is required or consulted (§3, out of scope).
- `--app overseer`: unchanged; no ownership record is required or consulted.

The check MUST NOT alter exit codes, output, or behaviour for the two unchanged roles.

### R7 — The old inference is removed, not guarded

Every place where the worker treats *the existence of a branch or a commit* as evidence
that a work product is complete and PR-able MUST be **deleted**. Adding an ownership check
in front of a retained inference does not satisfy this requirement. At minimum, the
implementer MUST address:

- `scripts/automation/lib/correlation.py` — `ResumeState.BRANCH_EXISTS` and
  `COLD_START_TABLE[BRANCH_EXISTS]` ("Branch exists — open PR (idempotent; branch already
  created)"). See §11, OQ-1: this interacts with the documented cold-start recovery
  contract (R6.1) and needs the human's answer before the exact edit is settled.
- `.claude/agents/worker.md` — the autonomous-loop steps that move from "branch exists /
  commits present" to "open PR" (notably the step-8.9 → step-9 sequence and the branch
  guidance at ~line 304).
- `bootstrap/worker-cron-prompt.md` — Step 5 ("Open PR … then STOP") and any Step 1/Step 2
  language that lets branch or commit presence stand in for "this is my finished work."

The implementer MUST grep for and enumerate any further sites; the list above is a floor,
not a ceiling. Each site is either deleted or replaced with a record lookup — never both.

### R8 — The record must not create a new committed-artifact surface

The ownership record MUST NOT be a repo-tracked file committed onto the working branch. It
is machine-local, per-cycle operational state, not a project artifact. Rationale: a tracked
per-branch state file reintroduces exactly the shared-file merge-conflict class that #888
was created to eliminate, and would leak operational state into every PR diff. The store
MUST NOT be a location that a PR diff can carry between machines.

### R9 — Refusal is observable

A refusal under R4/R5 MUST emit an audit event recording, at minimum: the branch name, the
role (`worker`), the reason class (no record / stale record / wrong cycle / unreadable),
and a timestamp. Events go through the standard audit-log writer (`audit/log/`, per #888).
The event lets an operator distinguish "the worker did nothing because there was nothing to
do" from "the worker built something and was correctly refused a PR."

### R10 — Governance docs state the rule

`.claude/agents/worker.md` and `bootstrap/worker-cron-prompt.md` MUST state the ownership
rule in the affirmative — *the worker opens a PR only for a branch it created in this
cycle; ownership is recorded, never inferred* — at the point where PR opening is described.
If `contract/OVERSIGHT-CONTRACT.md` describes the worker's PR-opening obligations, it MUST
be updated consistently.

### R11 — Branch deletion on merge (ALREADY SATISFIED — verification only)

Merged branches MUST be deleted automatically. **This is already satisfied at the GitHub
repo-settings level**, verified 2026-08-02:

```
gh api repos/thurlow-research/HumanOversightSystem --jq '.delete_branch_on_merge'  →  true
```

**No implementation is required.** This requirement is satisfied by repository configuration,
not by code, and its acceptance criterion (§8) is a verification checkbox only. The
implementer MUST NOT add code to delete branches. Consumer repositories that install HOS are
expected to set the same repo setting; documenting that expectation is optional here and is
**not** a blocker for this issue.

---

## 6. What Must NOT Change

Stated explicitly so reviewers do not read scope creep into the change:

| Surface | Required treatment |
|---|---|
| `submit_pr.sh --app human` + `--confirmed` | **Unchanged.** Governed separately; not implicated in this defect. No ownership record required. |
| `submit_pr.sh --app overseer` | **Unchanged.** The overseer creates no branches. |
| Overseer PR-review / merge-authority logic | **Unchanged.** The issue explicitly verified the overseer behaved correctly. |
| Issue selection, triage, claim protocol, cid derivation | **Unchanged**, except for the inference removal required by R7. |
| Pre-PR readiness gate (#317) | **Unchanged.** Ownership is an additional, independent precondition — not a replacement for, and not merged into, the readiness gate. |
| Worktree/clone isolation | **Unchanged** in this issue; separate hardening. |

---

## 7. Testing Requirements

- **T1 — Regression (load-bearing, the #967 scenario).** A foreign in-progress branch
  carrying a commit for a `needs-ai` issue is present when the worker fires, with **no**
  ownership record for it. Assert: **no PR is opened** on that branch, and the refusal is
  observable per R9. This test MUST fail against the pre-fix behaviour.
- **T2 — Happy path.** A branch created through the R1 branch-creation step, in the current
  cycle, passes the R4 check and reaches the existing push/PR path unchanged.
- **T3 — Stale/foreign record variants.** Enumerate and assert refusal for: no record;
  record for a different branch; record from a different (prior) cycle; record with
  non-`worker` role scope; malformed/unreadable record (R3/R5).
- **T4 — Role isolation.** `--app human --confirmed` and `--app overseer` behave
  identically before and after the change, with no ownership record present (R6).
- **T5 — No-override.** No flag, environment variable, or argument combination permits
  `--app worker` to open a PR without a valid record (R5).
- **T6 — Inference removal (structural).** A check asserting the deleted inference sites do
  not reappear: no code path derives "PR-able" from branch existence or commit presence
  (R7). A grep-style guard test is acceptable.
- **T7 — Record is not committed.** Assert the ownership store is not tracked by git and
  cannot appear in a PR diff (R8).

All work runs through `scripts/framework/run_tests_inner_loop.sh` and
`scripts/oversight/run_validators.sh`.

---

## 8. Acceptance Criteria

Verbatim from the human decision on #967 (2026-08-02):

- [ ] Worker opens a PR only for a branch it created during the current cycle; branch
      ownership is recorded, not inferred
- [ ] Worker never opens a PR for a branch created by another session, whatever its commits
      or issue label
- [x] Branches are deleted on merge — **already satisfied**; verified 2026-08-02 via
      `gh api repos/thurlow-research/HumanOversightSystem --jq '.delete_branch_on_merge'` → `true`.
      Repository-settings level, not code; no implementation required.
- [ ] Regression test: a foreign in-progress branch carrying a `needs-ai` commit is present
      when the worker fires, and no PR is opened
- [ ] The old "commit on a `needs-ai` branch implies completion" inference is removed from
      the worker, not merely guarded

Supplementary criteria from this spec (not part of the human's list, additive):

- [ ] `--app human --confirmed` and `--app overseer` are byte-for-byte unchanged in
      behaviour (§6, T4)
- [ ] Refusals are auditable (R9)
- [ ] The ownership store is not repo-tracked (R8, T7)

---

## 9. Threat Model / Scope Boundary (informative — prevents over-engineering)

The ownership record is written by the same session it later authorizes. It is therefore
**a correctness guard against cross-session confusion, not a security boundary against a
misbehaving agent.** An agent with shell access could write a record for any branch. That is
accepted and in-scope-by-design: the failure this issue exists to prevent is *accidental*
adoption of another session's in-flight work, not *adversarial* PR opening.

Implication for reviewers and technical-design: do **not** specify signing, tamper-evidence,
or a trusted-writer mechanism for the record. Do ensure the record cannot be produced
*incidentally* by a non-worker session (R2), which is the actual failure mode.

---

## 10. Risk Tier and Review Routing

**HIGH.** This change touches the autonomous worker's PR-opening authority — the same class
of governance-critical surface the #556/#558 pipeline-discipline rules exist to protect, and
the chokepoint through which every bot-authored PR in the system passes. Downstream agents
MUST route this as HIGH, **not** LOW/MEDIUM, notwithstanding the change's likely small
diff size. Two specific failure modes justify the tier:

1. **Fail-open regression** — an ownership check that silently passes when the store is
   missing restores the exact #967 behaviour while appearing fixed.
2. **Fail-closed lockout** — an over-strict check that refuses the worker's *own* branches
   halts autonomous delivery entirely (every cycle builds, then cannot submit), and it will
   look like "the worker had nothing to do."

The blast radius of an error is the entire autonomous build loop; the mitigation is T1+T2
run together, so both directions are covered by a test.

---

## 11. Open Questions (for architect / human)

**OQ-1 — Cold-start resume of a prior cycle's branch. (Needs a HUMAN answer; blocks the
exact shape of R7.)** `correlation.py:already_exists` currently returns `BRANCH_EXISTS` and
`COLD_START_TABLE` instructs "Branch exists — open PR," which is documented recovery
behaviour (R6.1 / ADR-2): a worker that crashes after pushing commits but before opening a
PR resumes on the next cycle. Strict application of the 2026-08-02 decision ("branches it
created **in its own work cycle**") makes a prior cycle's branch **foreign**, which removes
that recovery path. The two cannot both hold as written.

*Until the human resolves this, the fail-closed reading governs (R3): a record from a prior
cron invocation does not authorize the current invocation, and a crashed cycle's branch is
rebuilt fresh rather than resumed.* The accepted cost is orphaned branches from crashed
cycles. The architect should surface the trade-off; the pm-agent will not extrapolate a
per-cid-durable record into the spec without the human's word, because it would re-admit
"a branch exists for this cid, therefore it is mine" through the back door.

**OQ-2 — The bounced-PR / CHANGES_REQUESTED update path.** `worker-cron-prompt.md` Step 1
and `worker.md` §re-entry have the worker push fixes to the branch of an **existing open PR**
it authored — a branch created in a *prior* cycle. That path *updates* a PR rather than
opening one, but it currently flows through the same `submit_pr.sh`. Proposed reading, for
architect confirmation: **existing PR authorship by the worker bot is itself a recorded
(not inferred) ownership fact and is sufficient to update that PR's head branch; it is never
sufficient to open a new PR.** If the architect disagrees, or if the mechanics of "update vs
open" cannot be distinguished at the chokepoint, this becomes a second human question.

**OQ-3 — Who mints cycle identity, and where does the record live?** `bin/hos-cron` mints no
per-cycle identifier today. Preference (non-binding): the **launcher** mints it and exports
it to the session, so cycle identity is not at the agent's discretion. Store location
(e.g. under `${HOS_STATE_DIR:-$HOME/.hos}`, alongside the existing `locks/`, `last-run/`
dirs) is technical-design's, subject to R8.

**OQ-4 — Consumer projects.** `submit_pr.sh` and the worker agents ship to consumer repos
(the #967 incident happened in CondoParkShare). This spec assumes the enforcement is
**framework-wide with no per-project opt-out**. Architect to confirm there is no install-time
or `config.sh` toggle, and to confirm nothing in the installer needs to provision the store.

**OQ-5 — Multi-project cron.** `hos-cron` takes `--project`; two projects' worker cycles can
run concurrently on one machine. The record's key space must not collide across projects.
Flagged for technical-design; no product decision needed unless the architect finds one.

**OQ-6 — Milestone.** #967 is labelled **v0.6.0 (Astro & JS Support)**, but by the repo's own
triage rule (`docs/planning/README.md`: v0.5.1 = bug/governance gap in shipped code) this is a
v0.5.1-shaped governance bug with no Astro/JS content. Flagged for human re-triage; not a
blocker for design work.

---

## HOS Self-Flag (spec authoring)

```
RISK: HIGH
```

**Change classification: STRUCTURAL.** This document specifies new required behaviour
(an ownership record, a new refusal path in `submit_pr.sh`, removal of an existing
completion inference) — new requirements and a new enforcement point that did not exist
before. It is written **against an explicit human decision already given on #967**
(2026-08-02), which is the required sign-off for the structural content in §2 and §8. The
material *not* covered by that decision is confined to §11 and is raised as open questions
rather than written into the requirements.

```
BLAST RADIUS: The autonomous worker's ability to open PRs at all. A fail-open
implementation restores the #967 defect while appearing fixed; a fail-closed-too-far
implementation silently halts autonomous delivery (every cycle builds, none submits).
Rollback: revert the ownership check in submit_pr.sh (single chokepoint) and restore the
prior worker prose; the record store is inert if unread.
```

## Human Review Required

**§2 items 3–4 and R7 — "deleted, not guarded."** Review for correctness: the requirement
that the old inference be *removed* rather than wrapped is the load-bearing part of the
human's decision and the easiest to satisfy superficially. Verify at implementation review
that no retained code path still derives "PR-able" from branch or commit existence.

**§11 OQ-1 — cold-start recovery conflict.** Review for correctness: strict per-cycle
ownership removes the documented `BRANCH_EXISTS` crash-recovery path. This spec applies the
fail-closed reading pending your answer; confirm that is what you intend, or state that a
record durable per-cid across cycles is acceptable.

**§11 OQ-2 — bounced-PR update path.** Review for correctness: confirm that pushing fixes to
an already-open worker-authored PR remains permitted, and that this spec's reading (PR
authorship = recorded ownership, sufficient to update, never to open) matches your intent.

**R11 / §8 third criterion — branch deletion.** Review for security/process: verified `true`
via repo settings on 2026-08-02 and marked satisfied with no code. Confirm you accept a
repo-setting-level satisfaction rather than an enforced check.

```
CONFIDENCE: 88%
Basis: High confidence on the problem statement, the decision restatement, the scope
boundaries (§3/§6), and the acceptance criteria — all sourced directly from the issue and
the human's 2026-08-02 comment. Lower confidence on the completeness of the R7 inference-site
enumeration (correlation.py's COLD_START_TABLE was found by inspection; other sites may exist
in the worker's raw-tool-call flow, which is prose-governed and not fully greppable) and on
OQ-1's resolution, which materially shapes R3 and R7 and is not mine to decide.
```
