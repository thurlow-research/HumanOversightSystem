# ADR-037 — Worker branch ownership: PR-opening authority is per-cycle and recorded; the ownership record is a necessary precondition and never a completion signal

**Status:** **ACCEPTED — GO.** `technical-design` is cleared to proceed immediately. All five open questions (SPEC-967 §11 OQ-1 … OQ-5) are **resolved here**; none is escalated as blocking. **OQ-1 is architecture and I BIND it (AD-1)** — the fail-closed per-cycle reading governs, and the trade-off it was thought to cost is very largely illusory (§0, VF-1/VF-2/VF-3). Two consequences carry non-blocking notes to the human (§3); neither gates design or build.
**Date:** 2026-08-02
**Author:** architect
**Issue:** #967 · **Milestone:** v0.6.0 as labelled (see §3, N3) · **Risk tier: HIGH** (confirmed — §4)
**Inputs:** `docs/specs/SPEC-967-worker-branch-ownership.md` (pm-agent, 2026-08-02); the human's decision comment on #967 (2026-08-02) read in full; the human's superseded 2026-07-30 comment; my own verification against the working tree (§0).
**Consumers:** `technical-design` (next), then `coder` → the standard review chain.
**Does not re-open:** SPEC-967 §2 (ownership-vs-lock-vs-ready-signal). That is human-decided and closed. Nothing below revisits it; AD-1 and AD-4 are *readings of* that decision, not amendments to it.

---

## 0. Verification findings — I read the code the spec reasons about

pm-agent's §11 was written from inspection of `correlation.py` alone. I read the call graph, the actual branch names in use, the chokepoint, and the launcher. **Four findings materially change the cost of OQ-1, and two change the shape of OQ-2.** Every citation below is from the Worker working tree at `/home/scott/Code/HumanOversightSystem/Worker`.

**VF-1 — `BRANCH_EXISTS` cannot fire in practice, because it keys on a branch-name convention the worker does not use.** `correlation.already_exists()` looks up `branch_name(cid)`, which is hard-coded to `f"hos/auto/{cid}"` (`correlation.py:90-92`). No branch in this repository has ever used that form. Verified: `git branch -r` → `worker-1185-sandbox-template-reconcile`, `forward-port/*`, `docs/*`, `release/*`; local branches → `feat/1034-…`, `docs/889-…`, `chore/895-…`. `worker.md:304` itself prescribes `feat/<cid>-*` / `fix/<issue>-*` / `forward-port/<desc>` — a *third* convention, also not `hos/auto/<cid>`. So the lookup misses every real branch, and `already_exists()` falls through `BRANCH_EXISTS` to `CLAIM_PRESENT`/`NOT_STARTED` every time.

**VF-2 — the resume path is not wired into the autonomous loop at all.** `grep` for `already_exists` across the tree returns exactly two live sites: `worker.md:256` (prose, the "per-task worker chain") and `tests/automation/test_correlation.py`. **No executable code calls it.** More decisively, `bootstrap/worker-cron-prompt.md` — the prompt `bin/hos-cron` actually feeds the session each cycle — contains **no idempotency precheck whatsoever**. Its LOOP is Step 0 triage → **Step 1 "check open PRs"** (remote REST) → Step 2 pick issue → Steps 4/4b gates → Step 5 open PR. The recovery that the autonomous worker actually performs is *remote-PR-state* recovery, not branch-existence recovery.

**VF-3 — the window `BRANCH_EXISTS` would recover is a few seconds inside one script.** `get_branch` is a REST call (`github.py:151-156` → `get_ref`), so `BRANCH_EXISTS` means a **pushed** branch with no PR. The only way to reach that state through the sanctioned path is a crash between `git push` succeeding (`submit_pr.sh:146`) and `gh pr create` succeeding (`submit_pr.sh:152`) — six lines and one API call apart, inside a single `set -euo pipefail` script invocation.

**VF-4 — `submit_pr.sh` has no update mode, and no knowledge of `$PROJECT`.** It unconditionally does `git push` then `gh pr create` (`:146`, `:152`); `gh pr create` against a branch that already has an open PR fails. There is no `--force`. It resolves `REPO_SLUG` from the `origin` remote (`:121-124`); it never reads `projects.conf` and has no `--project` argument. **This is decisive for OQ-2 and OQ-5.**

**VF-5 — the bounce path may not traverse the chokepoint at all.** `worker-cron-prompt.md` Step 1 and `worker.md:240` say "fix, push, STOP" and name **no script**. `ls bootstrap/` shows `create_issue.sh`, `post_comment.sh`, `submit_pr.sh` — **there is no push-only wrapper.** So today's bounce push is either hand-rolled (contrary to `CLAUDE.md`) or does not happen through a committed path. pm-agent's OQ-2 premise — "it currently flows through the same `submit_pr.sh`" — is **not established**, and designing as if it were is the fastest route to the §10 fail-closed-lockout failure mode.

**VF-6 — no cycle identity exists, but the namespacing idiom for it already does.** `grep -rn "cycle_id\|CYCLE_ID\|cycle-id"` across `scripts/`, `bin/`, `bootstrap/` → **zero hits**. `cycle_log.py` writes cycle *events* but mints no identifier. Meanwhile `bin/hos-cron:124-133,182` already namespaces every piece of per-cycle machine-local state by `(role, project)` under `${HOS_STATE_DIR:-$HOME/.hos}` — `locks/hos-cron-${ROLE}-${PROJECT}.lock`, `last-run/${ROLE}-${PROJECT}`, `wakeup/${ROLE}-${PROJECT}`, `suspend/${PROJECT}`. OQ-5's requirement is not novel; it is the house pattern.

**VF-7 — launcher and chokepoint ship and upgrade together.** `bootstrap/hos_install.sh:1822-1841` installs all of `bin/` (including `hos-cron`) into the target repo, and the generated crontab lines invoke `$TARGET_REPO/bin/hos-cron` (`:2429`, `:2433`). So a consumer's launcher and its `submit_pr.sh` come from one install and move together. Version skew between them is bounded — but *not* zero (a machine may point cron at another checkout's `bin/hos-cron`), which is why AD-6 requires a diagnosable refusal message rather than a bare non-zero exit.

**VF-8 — R11 does not sweep the orphans AD-1 accepts.** `delete_branch_on_merge` deletes branches **on merge**. An orphan from a crashed cycle is by definition never merged, so R11 provides no cleanup for it. The spec's "accepted cost" therefore comes with a small, real, and currently unowned operational obligation (§3, N1).

---

## 1. The organizing principle I bind

The human's decision replaced an *inference* with an *ownership record*. The single most likely way to satisfy that decision superficially — and the failure mode I am writing this ADR to prevent — is to let the ownership record quietly become the new completion signal. So I bind the principle first, and every decision below follows from it:

> **The ownership record is a NECESSARY precondition for opening a PR. It is NEVER a SUFFICIENT one, and it is never evidence that work is finished.**
> "This cycle created this branch" and "this branch holds a finished, reviewed work product" are different facts. The record carries only the first. The second is, and remains, the business of the review chain, the sign-off register, the oversight-evaluator verdict, and the #317 readiness gate (`SPEC-967` §6 keeps those independent — correctly).

Every reading of the human's decision that turns the record into a *reason to open a PR* rather than a *permission to* is wrong, and AD-1 and AD-4 are the two places where that mistake would actually be made.

---

## 2. Decisions

### AD-1 — OQ-1 RESOLVED: this is architecture, not a human call. The **fail-closed per-cycle reading is BOUND.** A record from a prior cron invocation never authorizes the current one. (BINDING.)

I considered the task's three options — (a) confirm fail-closed, (b) propose per-issue/cid-durable cycle identity, (c) escalate — and I bind **(a)**, decisively, for four independent reasons. Any one of the first three would be sufficient; together they leave no genuine open question.

**1. The human's words settle it, and the one phrase that appears to cut the other way does not.** The decision reads: *"The worker opens PRs **only for branches it created in its own work cycle**"* and *"'A commit exists on a `needs-ai` branch' stops being evidence of anything. That inference is deleted, not refined."* "In its own work cycle" is explicit, and §4 of the spec defines a work cycle as one `hos-cron` invocation and the session it launches. The counter-phrase is *"locks go stale; ownership does not."* Read in context that is an argument about the **foreign-branch** direction — a stale lock stops protecting and lets you grab someone else's branch; ownership never stops being true, so it never lets you grab someone else's branch. It is not an argument that a *prior cycle's own* branch is resumable. The reconciliation is exact and I bind it as the vocabulary:

> **The ownership FACT is durable** — "cycle C1 created branch B" is true forever, and that is what never goes stale.
> **The AUTHORITY the fact confers is per-cycle** — only the cycle named in the record may act on it.
>
> Ownership does not decay. Authority does not transfer.

**2. Option (b) re-admits the deleted inference in its most dangerous form.** Trace it: cycle C1 creates branch B for issue/cid X and writes a cid-durable record. C1 crashes *mid-review* — after the coder committed, before the code-reviewer approved (which is **precisely the CondoParkShare state**). C2 fires, resolves cid X, finds a durable record for B, concludes "mine," and opens a PR on unreviewed code. The actor changed from an interactive session to a prior worker cycle; **the harm is byte-identical to #967** — a PR opened on a work product whose review status the opening cycle has no knowledge of. This is exactly the back door pm-agent refused to walk through without the human's word, and pm-agent was right to refuse. I am not extrapolating it either; I am ruling it out.

**3. Per-cycle scoping is not arbitrary strictness — it is the only scope under which the record can mean anything.** The evidence that makes a PR legitimate is the review chain's output: the sign-off register, the second-review artifact, the oversight-evaluator verdict, the 8.9 readiness result. All of it lives in `.claudetmp/` — machine-local, per-session, non-durable temp state. **A later cycle cannot see it.** So a cross-cycle record would authorize a PR at exactly the moment the evidence justifying it has evaporated. Scoping authority to the cycle aligns the record's lifetime with the lifetime of the evidence that makes acting on it safe. That alignment is the architectural content of the human's "its own work cycle," and it is why I can rule this rather than route it.

**4. The cost the trade-off was thought to carry is very largely illusory (§0).** OQ-1 frames this as sacrificing "documented crash-recovery behaviour." What is actually being given up is: a state (`BRANCH_EXISTS`) that **cannot fire**, because it keys on a branch name nothing uses (VF-1); reached through a function that **nothing executes** (VF-2); absent entirely from the prompt the cron actually runs (VF-2); recovering a window that is **six lines of one script wide** (VF-3). The real crash recovery in the autonomous loop — Step 1's remote open-PR inspection, the claim protocol's stale-claim reclamation, and `ResumeState.PR_EXISTS`/`GATES_COMPLETE`/`MERGED` — is **untouched by this decision** (AD-2) and covers every state past PR creation. pm-agent stated the conflict correctly from the code it read; the code it did not read shows the conflict is nearly theoretical.

**Therefore, BOUND:** a crashed cycle's branch is **foreign** to every subsequent cycle. The work is rebuilt fresh (AD-3). The orphaned branch is inert: it is never PR'd, never merged, never read for control flow. Its bounded cost is namespace and a sweep (§3, N1 — a note, not a gate).

**Why this does not require the product-boundary checkpoint.** I applied the CORE test. This is not a new decision with a product consequence — it is a *reading of a human decision already given*, in the direction the human's own text points, on a failure mode (crash-and-resume) whose observable behaviour today is "nothing happens" (VF-2). The one genuine consequence is the orphan-sweep obligation, which is small, bounded, inert, and unowned *today* as well. I route it as a **non-blocking note** (§3, N1) rather than a gate. Consistent with "when in doubt, route it," I am routing the consequence while binding the decision — design proceeds now.

### AD-2 — R7's exact edit, which OQ-1 was blocking: delete `BRANCH_EXISTS` **only**. `CLAIM_PRESENT`, `PR_EXISTS`, `GATES_COMPLETE`, `MERGED` all survive unchanged. (BINDING.)

This is the edit the spec said could not be settled until OQ-1 was answered. It is settled:

- **DELETE** `ResumeState.BRANCH_EXISTS` and `COLD_START_TABLE[BRANCH_EXISTS]`, and the `if branch_found: return ResumeState.BRANCH_EXISTS` branch (`correlation.py:161-162`) **together with the `get_branch` call at `:147-148` that feeds it**. Deleting the enum member while leaving the remote branch lookup in place leaves a dead API call that the next reader will re-wire — the "deleted, not guarded" requirement (R7) is about the inference, and the lookup *is* the inference.
- **KEEP** `MERGED`, `GATES_COMPLETE`, `PR_EXISTS`, `CLAIM_PRESENT`, `NOT_STARTED`. These derive from **remote PR state and posted claim envelopes** — records, not inferences from local branch shape. They are the actual cold-start recovery and they are not implicated in #967.
- **KEEP** cid derivation, `branch_name()`'s existence as the single naming owner, `pr_title()`, and the claim protocol. §6 puts these out of scope and I confirm it.
- **Correct the module docstring.** `correlation.py:5-8` claims "the cid is the ONLY mechanism that prevents duplicate work" on the strength of two racing workers deriving the same *branch name*. After this change — and in truth already, per VF-1 — deduplication rests on the **claim protocol** and on **remote PR/merge state** (`PR_EXISTS`/`MERGED`), not on branch-name collision. Leaving the docstring asserting a property the code no longer has is the documentation-reality drift class (#1123). Fix it in the same change; it is two sentences.
- **Test consequence, stated so it is not mistaken for a regression:** `tests/automation/test_correlation.py` asserts `BRANCH_EXISTS` (`:195`) and iterates `for state in ResumeState: assert state in COLD_START_TABLE` (`:269-270`). Those assertions are *supposed* to change. The table-completeness invariant must survive over the reduced enum.

**Anti-loophole:** R7 is satisfied only if no code path derives "PR-able" from branch or commit existence. Replacing `BRANCH_EXISTS` with an ownership-record lookup **inside `already_exists()`** would violate it — that would make the record a resume signal, i.e. a completion signal (§1). The ownership check belongs at the chokepoint (R4) and nowhere else.

### AD-3 — Branch names must be unique per cycle, because AD-1 guarantees a name collision on rebuild. (BINDING — architecture; exact naming scheme is `technical-design`'s.)

AD-1 says a crashed cycle's work is rebuilt fresh. If branch names are derived from the issue or cid alone — which every convention in use does (`worker-1185-…`, `feat/1034-…`, `hos/auto/<cid>`) — the rebuilding cycle derives **the same name as the orphan**. Then: `git checkout -b` fails locally against the orphan, or, if the orphan was pushed (VF-3), the push in `submit_pr.sh:146` is rejected non-fast-forward. Either way the worker is wedged in a way that looks like "the ownership check broke everything" — §10's failure mode 2, arrived at from an unexpected direction.

**BOUND:** the R1 branch-creation seam MUST produce a name that cannot collide with a branch left by any earlier cycle. Binding cycle identity into the name is the obvious way and it makes the collision class structurally impossible; a detect-and-suffix scheme is acceptable if it is deterministic and fail-closed. What is **not** acceptable is reusing an existing branch of the same name, or force-pushing over it — both are "adopt a branch this cycle did not create," which is the defect.

### AD-4 — OQ-2: the **principle is CONFIRMED**; the **mechanism is BOUND**, and pm-agent's premise about the call path is **rejected as unverified**. (BINDING.)

**Principle — confirmed, and it is the strongest available form of "recorded, not inferred."** Existing PR authorship by the worker bot *is* a recorded ownership fact, and it is a better one than the local record: it is server-side state at GitHub, established by the act of creation, not derivable from any local branch shape, and not producible by an interactive session under a different identity. It is **sufficient to update that PR's head branch; never sufficient to open a new PR.** Confirmed as written.

**Mechanism — bound, because "confirmed in principle" is where this gets implemented wrongly.** VF-4/VF-5 show the chokepoint has no update mode and the bounce path may not reach it. Four binding constraints:

1. **The discriminator MUST be an explicit caller-declared mode.** Update and open are separate, explicitly named operations (`--update-pr <N>` on `submit_pr.sh`, or a sibling wrapper — `technical-design`'s call). **Forbidden: try-create-then-fall-back-to-update-on-error.** Inferring "this must be mine" from `gh pr create` failing with "a pull request already exists" is the same inference class the human deleted, rebuilt out of an error string.
2. **Update-mode authority MUST be verified server-side at call time, never asserted by the caller.** The script itself queries the PR by number and requires *all* of: PR is **open**; `head.ref` **equals** the resolved `--head`; and `user.login` **equals** the worker bot login. Any mismatch, or any inability to reach the API, is a refusal (R5 applies to this predicate exactly as it does to R4). A caller-supplied "this is mine" flag is worth nothing.
3. **Open mode MUST additionally refuse when an open PR already exists for the head branch.** Symmetric to (1), and it converts a confused caller into a clean refusal instead of a `gh` error the agent might route around.
4. **Force-push is a distinct, separately-gated capability.** `worker.md` Step 1.1 and `worker.md:335` contemplate force-pushing to a PR head on conflict, and `submit_pr.sh` supports no `--force` today. If update mode ever admits force-push it MUST carry the same server-side author check plus the AD-1 rule that the target PR was authored by the worker bot — because force-pushing over a PR head one does not own is a *destructive* form of the #967 defect, and it is exactly what the human orchestrator had to do to recover from it.

**Rejected premise, and this is the single largest lockout risk in the build.** pm-agent wrote that the bounce path "currently flows through the same `submit_pr.sh`." VF-5 does not support that; there is no push-only wrapper and the prose names no script. **`technical-design` MUST establish empirically how the bounce push happens today before specifying R4's placement.** If R4 is bolted onto a code path the bounce push does traverse, every bounced PR from a prior cycle hits "no valid record for this branch" → refusal → **the worker can never respond to review feedback again**, and the operator sees a worker that quietly stops delivering (§10, mode 2). This is the one place where a correct-looking implementation of this spec halts the autonomous loop.

**Scope discipline:** building a proper update-mode wrapper may be larger than #967. The **minimum** obligation for this issue is that R4's enforcement be placed so that it governs **PR opening only** and cannot capture the update/bounce path. If `technical-design` finds the bounce path is hand-rolled, that is a **pre-existing gap** → file it as a separate issue (§3, N2), do not absorb it into #967.

### AD-5 — OQ-3: **YES — the launcher mints cycle identity.** Its *absence* is the fail-closed hinge and simultaneously satisfies R2's role-scoping requirement. (BINDING on the source, the export, and the absent-value semantics; the exact format is `technical-design`'s.)

Plainly: **`bin/hos-cron` mints one identifier per invocation and exports it into the launched Claude session's environment** (name it `HOS_CYCLE_ID` unless `technical-design` has a better reason). Cycle identity is **never** at the agent's discretion.

Three reasons, the third being the one that matters most:

1. `bin/hos-cron` **is** the process boundary that §4 defines a work cycle to be. Minting anywhere else means the identifier and the thing it identifies are different objects.
2. It is one site, already responsible for every other per-cycle artifact (VF-6), already emitting `cycle-start`.
3. **An agent that mints its own identity can choose to re-mint a prior one** — accidentally (re-reading state) or by prompt injection (`worker-cron-prompt.md` §SECURITY treats issue and PR text as untrusted). Launcher-minted identity removes that discretion structurally.

**The absent-value semantics are the load-bearing part, and I bind them:**

> If `HOS_CYCLE_ID` is unset or empty, **no ownership record can be valid** (R3.2 cannot be satisfied), and `submit_pr.sh --app worker` **refuses**. There is no default, no fallback, no "derive one if missing."

This is not merely R5 compliance. It is **how R2's "a record MUST NOT be producible by an interactive/human session" is achieved** — an interactive human-proxy session is not launched by `hos-cron`, therefore has no cycle id, therefore cannot write a valid record *or* pass the check, with no role-detection heuristic anywhere. The role scoping falls out of the minting boundary. `technical-design` should recognise this as the mechanism rather than adding a separate role check on top; a redundant one is harmless, a *substitute* one is not.

**Shape (indicative, so nobody guesses):** opaque, per-invocation-unique, and collision-free across concurrently-running roles and projects on one machine. `<UTC compact timestamp>-<role>-<project>-<pid>` or a `uuid4` both qualify. Timestamp-only does not (two projects fire in the same second). PID-only does not (`hos-cron:176-182` already documents PID reuse across reboots as a live failure class — #1002). Exact format is `technical-design`'s; **uniqueness under concurrency and non-reuse across reboots are mine, and they are requirements.**

### AD-6 — OQ-4: **CONFIRMED — framework-wide, no opt-out, no installer provisioning.** (BINDING.)

- **No opt-out, and specifically no `config.sh` key and no install-time flag.** The incident occurred in a *consumer* repo (CondoParkShare); a per-project toggle would leave unprotected precisely the class of deployment where the defect actually fired. R5 already forbids override flags and environment escapes; a config key is the same escape hatch with a slower fuse. This follows the house rule from ADR-036 AD-6: **configuration may only narrow what is permitted, never widen it.**
- **The installer provisions nothing.** The store MUST be **self-provisioning on first write** (create-if-absent under the state dir). Rationale: an installer-provisioned store makes correct operation depend on install history, so any consumer that upgrades by a path that skips provisioning gets a worker that halts. Self-provisioning removes install order from the correctness argument entirely.
- **The refusal message MUST be diagnosable, and this is a requirement not a nicety.** Both failure directions of §10 look identical in the log — a worker that had nothing to do and a worker that was refused both produce a quiet cycle. R9's audit event covers the operator-facing half; the message on stderr must name **the branch**, **the reason class**, and — when `HOS_CYCLE_ID` is absent — say so explicitly, because that specific case is the signature of launcher/chokepoint version skew (VF-7) and is otherwise near-impossible to diagnose from the outside.

### AD-7 — OQ-5: **CONFIRMED, and the key shape is bound — but not the way R2 states it.** (BINDING on the constraint; storage location and format remain `technical-design`'s.)

R2 says the record is "keyed by branch name." **That is insufficient and I amend it.** Two projects on one machine routinely produce identically-named branches (`worker-12-fix-x` is not distinctive), and per VF-6 the natural store lives under a machine-global `${HOS_STATE_DIR:-$HOME/.hos}` shared by every project. A branch-name-only key lets project A's record authorize a PR on project B's same-named branch — a fresh instance of the exact class this ADR exists to close.

**BOUND — the lookup key MUST uniquely identify the (repository-or-clone, branch) pair**, such that:
- a record written for branch `B` in project/clone P is **never** valid for branch `B` in project/clone Q; and
- **both ends derive the key independently and deterministically from information each already has, with no new configuration.** This is a hard constraint, not a preference: `bin/hos-cron` knows `$PROJECT` and `$REPO_ROOT`; `submit_pr.sh` knows **neither** — it has no `--project`, never reads `projects.conf`, and resolves only `REPO_SLUG` from the `origin` remote (VF-4). A key built from `$PROJECT` therefore cannot be computed at the checking end without adding a parameter. Prefer a component both ends can compute: the resolved repo slug, or the realpath of the repository root.
- **Watch the two-clones-one-slug case.** Worker and Human clones of the same repo share a slug; a slug-only key does not distinguish them. Under AD-5 this is already harmless (the Human clone has no cycle id and cannot write a valid record), but `technical-design` should choose knowingly rather than discover it later. Note that a store held **inside the repository's own `.git/` directory** would satisfy R8 by construction (untracked by definition — it can never appear in a PR diff, which is precisely what R8/T7 demand) and would make the clone-scoping automatic. I am not choosing the location; I am pointing out that one candidate discharges two constraints for free.
- **Full record contents** remain per R2 — cycle identity, role scope, timestamp — with the **(clone, branch)** pair as the lookup key and **cycle identity checked as a value**, not folded into the key. Folding cycle identity into the key would make a stale record simply *not found*, losing the ability to distinguish "no record" from "wrong cycle" — a distinction R9 explicitly requires the audit event to report.

### AD-8 — Confirmations, so no reviewer reads negotiability into silence

I reviewed the rest of SPEC-967 for architectural soundness and **confirm it**, specifically: the chokepoint choice (R4 — `submit_pr.sh` is the right and only place; enforcement before token mint and push is correct, and it means a refusal never touches the network); fail-closed with no override (R5); worker-only enforcement with `--app human`/`--app overseer` untouched (R6 — and I note the human path's `--confirmed` is a *stronger* per-instance gate already, so adding an ownership requirement to it would be redundant, not safer); the not-repo-tracked store (R8 — correctly reasoned from #888); observable refusal (R9); the affirmative-statement doc requirement (R10); R11 as configuration-satisfied with no code; and the §9 threat model — **this is a correctness guard against cross-session confusion, not a security boundary.** I explicitly endorse §9's instruction: **no signing, no tamper-evidence, no trusted-writer mechanism.** An agent with shell access can write a record for any branch; that is accepted, and hardening it would buy nothing while adding a surface. And I confirm the **HIGH** tier (§10) — the blast radius is the autonomous loop's ability to deliver at all, and AD-3/AD-4 each add a distinct way to hit the lockout direction.

---

## 3. Notes and obligations — routed, none blocking

**N1 — Orphaned-branch sweep (to the human and `pm-agent`; NOT a gate).** AD-1 accepts orphaned branches from crashed cycles. VF-8 establishes that `delete_branch_on_merge` does **not** clean them (they never merge). This is a small new operational obligation with no owner. It is bounded and inert — orphans are never PR'd, never merged, never read for control flow, and after AD-3 never collide with new work. **Recommended:** file a separate low-priority issue for an orphan sweep (a stale `hos/`-namespace branch reaper, or a manual runbook line). **It is explicitly not a blocker for #967**, and #967 MUST NOT absorb it.

**N2 — The bounce path has no committed wrapper (pre-existing gap; file separately).** VF-5: the worker's "fix, push, STOP" path names no script, and `bootstrap/` contains no push-only wrapper, so the push is hand-rolled against `CLAUDE.md`'s own rule that pushes go through `submit_pr.sh`. This is a real gap that predates #967 and it is the reason AD-4's premise-rejection matters. **File as its own issue.** #967's obligation is only to place R4 so it cannot capture the bounce path.

**N3 — Milestone (OQ-6 — not mine, and not a blocker).** pm-agent is right that #967 is a v0.5.1-shaped governance bug with no Astro/JS content, and right that it is labelled v0.6.0. Milestone assignment is triage, not architecture. Design and build proceed under the label as it stands; re-triage if the human chooses.

**N4 — Human review items already correctly raised by pm-agent stand as raised**: §2 items 3–4 / R7 "deleted, not guarded" (AD-2 gives the exact edit; verify at implementation review), and R11's repo-settings-level satisfaction. AD-1 discharges the OQ-1 review item and AD-4 discharges the OQ-2 one; both are recorded here rather than left open.

**Startup-gap analysis (CORE discipline).** This is the **initial** architecture review for #967, not a reactive revision. No prior ADR covers this surface; no design or code sign-off has been issued against any superseded decision. **No sign-off is orphaned and none requires re-review.** The one adjacent artifact is `correlation.py`'s ADR-2/R6.1 lineage (`docs/specs/UNATTENDED-WORKER-TECH-DESIGN.md:371`), whose `BRANCH_EXISTS` contract AD-2 narrows. Because VF-1/VF-2 establish that path was never executed, nothing was ever built or approved *against the behaviour being removed* — the removal invalidates no approval. `docs/v0.6.0/REQUIREMENTS-034-sandbox-hang-detection.md:129-132` cites the cold-start model as a recovery assumption; its `ResumeState` reliance survives AD-2 intact (it needs `PR_EXISTS`/`MERGED` and stale-claim reclamation, none of which are touched), but **`technical-design` MUST confirm that** rather than take it from me, and say so in the design.

---

## 4. Where pm-agent was right, and where I differ

- **Right, and materially so:** the problem statement and its separation of *inference* from *signal*; the §3/§6 scope boundaries (especially keeping `--app human`/`--confirmed` out — importing an ownership requirement there would have been the obvious over-reach); R5's no-override posture; R8's reasoning from #888; the §9 threat model, which correctly pre-empts a reviewer demanding signing; the §10 two-directional failure analysis, which is the best part of the spec and which AD-3 and AD-4 both extend; and — decisively — **refusing to extrapolate a cid-durable record without the human's word.** That restraint was correct: AD-1's reason 2 shows the extrapolation would have re-admitted the defect.
- **Differed / sharpened, four places:**
  1. **OQ-1 is architecture, not a human question** (AD-1). pm-agent lacked the call-graph and branch-name evidence (VF-1/VF-2/VF-3) that shows the trade-off is nearly costless, and reasonably declined to rule without it. With that evidence the decision follows from the human's text; escalating would have stalled the build on a question the human already answered.
  2. **OQ-2's premise is unverified and I reject it** (AD-4). "It currently flows through the same `submit_pr.sh`" is not established (VF-4/VF-5), and designing on it produces the lockout.
  3. **R2's "keyed by branch name" is insufficient** and is amended to a (clone, branch) key with cycle identity as a checked value (AD-7) — with the concrete constraint that `submit_pr.sh` cannot compute a `$PROJECT`-based key at all.
  4. **R7's edit must remove the `get_branch` call, not just the enum member**, and must correct the now-false `correlation.py` docstring (AD-2) — otherwise "deleted, not guarded" is satisfied in letter only.

---

## 5. Cleared-to-build

**`technical-design` MAY proceed NOW**, against: AD-1 (per-cycle authority, fail-closed), AD-2 (the exact R7 edit), AD-3 (cycle-unique branch names), AD-4 (explicit-mode update path, server-verified authority, and the empirical check on the bounce path **first**), AD-5 (launcher-minted `HOS_CYCLE_ID`, absent ⇒ refuse), AD-6 (no opt-out, self-provisioning, diagnosable refusal), AD-7 (key shape), AD-8 (the confirmed remainder of the spec).

**`coder` follows the normal HIGH-tier routing.** Nothing in this ADR is held for a human, and no human clearance gates design or build. The four items `technical-design` must not get wrong, in order of how much damage they do:

1. **Establish how the bounce push actually happens before placing R4** (AD-4). This is the lockout.
2. **Make branch names cycle-unique** (AD-3). This is the other lockout.
3. **Do not let the ownership record become a resume or completion signal** (§1, AD-2). This is the silent re-introduction of #967.
4. **Absent `HOS_CYCLE_ID` must refuse loudly and by name** (AD-5, AD-6). This is the difference between a diagnosable halt and a silent one.

**Acceptance for this ADR** is SPEC-967 §8's criteria plus: T3 covers the AD-1 prior-cycle case explicitly; a test asserts the AD-4 update path is *not* captured by R4; a test asserts a same-named branch in a second project does not satisfy the check (AD-7); and T6's grep guard covers the removed `get_branch` call, not only the enum member (AD-2).

---

## Human Review Required

**RISK: HIGH** (confirmed, §10). The architecture *reduces* the governance risk that produced #967, and the residual risk is concentrated entirely in the fail-closed direction — an over-strict or mis-placed check silently halts autonomous delivery while looking like an idle worker. AD-3 and AD-4 exist specifically to bound that, and the §10 requirement to run T1 and T2 together is the proof obligation.

**CONFIDENCE: HIGH** on everything I read in this session against the working tree: `correlation.py` in full (including `branch_name`'s `hos/auto/` form and the absence of any executable caller), `github.py:get_branch`, `submit_pr.sh` in full, `worker-cron-prompt.md` in full, `worker.md` §§autonomous-loop/credentials/never-do, `bin/hos-cron`'s state-dir and locking conventions, `hos_install.sh`'s `bin/` coverage and generated crontab, and the live branch inventory. **LOWER** on how the bounce push is performed today — I established that no committed wrapper exists (VF-5), not what the agent does instead, which is why AD-4 makes that an explicit empirical obligation on `technical-design` rather than an assumption here.

**BLAST RADIUS:** the autonomous worker's ability to open PRs at all, on every consumer deployment — a fail-open implementation restores the #967 defect while appearing fixed; a fail-closed-too-far one halts delivery invisibly. Rollback remains the spec's: revert the check at the single chokepoint and restore the prior prose; the record store is inert if unread.

**Change classification: STRUCTURAL.** It specifies new required behaviour (a per-cycle ownership record, launcher-minted cycle identity, a new refusal path at the PR chokepoint, and removal of an existing completion inference) against an explicit human decision already given on #967 (2026-08-02). The material not covered by that decision was confined to SPEC-967 §11 and is **resolved here as architecture** (AD-1 … AD-7), with two bounded consequences routed as non-blocking notes (§3, N1/N2). Nothing in this ADR requires human clearance before design or build proceeds.
