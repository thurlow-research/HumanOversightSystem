# REQUIREMENTS-1542 — Script coverage for sandboxed Worker & Overseer: every autonomous action must be a single invocation of a committed script

**Status:** DRAFT for `architect`. Twelve product decisions escalated to the human (§6). One of them
(**Q1**) narrows the literal wording of a human ruling recorded the same day on #1357 and is
classified **structural** — `architect` MUST NOT bind it until the human rules. The remainder of this
document is settled and `architect` may proceed on it. Fifteen §0 verification findings were derived
from `origin/main` directly; **six of them correct or contradict the preliminary document**
(**VF-2**, **VF-3**, **VF-4**, **VF-8**, **VF-9**, **VF-11**) and change what must be built.
**Date:** 2026-09-10
**Author:** `pm-agent`
**Verified against:** `origin/main` @ `dfa9bf8e` (`docs(#1542): preliminary requirements`).
**Source issue:** #1542 (open, `needs-human`, v0.7.0 — Quality).
**Requirements input:** `docs/specs/PRELIMINARY-REQUIREMENTS-sandboxed-autonomous-roles.md`
(merged via PR #1543, 2026-09-10) — an *investigation product*, explicitly non-actionable. Treated
here as a hypothesis set, not as given.
**Reconciled against:** #1357 (open, `needs-human`, v0.7.0 — ruled 2026-09-10) and #1538 (open,
`needs-human`, v0.7.0 — ruled 2026-09-10). §3 is the binding resolution of the overlap.
**Blocks:** #1146 / #1053 (v0.7.4 — Sandboxing & Isolation). This issue is their script-coverage
prerequisite.
**Target chain:** `pm-agent` (this document) → `architect` (granularity + ownership decisions,
§6) → `technical-design` (per-script designs) → normal build steps.
**Consumers:** `architect` (next), then `technical-design`, then the implementing build steps.
**Scope note:** This document states WHAT and WHY only. Script names appearing below are *labels for
required capabilities*, not proposed filenames. File layout, language choice per script, function
signatures, flag spellings, JSON schemas, and CLI granularity are `architect`'s and
`technical-design`'s to decide — with the single exception of the granularity *principle* in §3.2,
which is escalated to the human because it bears on an existing ruling.

---

## 0. Verification findings — the preliminary document versus the repository

Every load-bearing claim in the preliminary document and in #1542's body was re-derived from
`origin/main` rather than accepted. Nine claims are confirmed; six are corrected. Line numbers are
`origin/main`'s (this session's clone is on an unrelated audit branch, so every citation below was
read via `git show origin/main:<path>`).

**Verification gaps, stated up front.** (a) Live GitHub *repository settings* — branch protection,
required status checks, CODEOWNERS enforcement — were not inspected; **Q9** turns partly on them.
(b) No sandbox policy was generated or executed for worker/overseer; the allowlistability judgements
below are applications of the rules recorded in `CLAUDE.md` § "Shell usage under the sandbox", not
measured outcomes. (c) The specialist-subagent command surface (§9 of the preliminary document) was
not inventoried; it remains deferred here for the same reason (see §5, NG-4). (d) The preliminary
document's inventory of *where* each operation is used inside `worker.md`/`overseer.md` was spot-
checked, not re-derived exhaustively; a full per-call-site census is `technical-design`'s work.

---

**VF-1 — CONFIRMED, with a refinement that matters.** Of `scripts/automation/lib/*.py` (21 modules),
exactly two have `if __name__ == "__main__"` blocks: `pr_readiness.py` and `cycle_log.py`. The
preliminary document's §6 premise holds. **Refinement:** only `pr_readiness.py` uses `argparse`.
`cycle_log.py`'s entry point is a hand-rolled positional parser (`_parse_args`, `:69`) taking
`<event> [key=value ...]`, and `log_event` (`:57`) **hardcodes `"role": "worker"`** into every record
it writes. That hardcoding is a live defect for any shared/both-roles logging surface and is
material to #1538 (§3.3).

**VF-2 — CORRECTS the preliminary document's open question (P14): `check_pr_files` has no CLI.**
`scripts/oversight/codeowners.py` defines `check_pr_files` at `:187` and `requires_human_approval` at
`:152`. The module has **no `__main__` block and no `argparse` import**. The preliminary document
flagged this "verify"; the answer is that the gap is real and P14 is a genuine requirement, not a
possible false positive.

**VF-3 — NEW, not in the preliminary document: there are two distinct `codeowners` modules.**
`scripts/oversight/codeowners.py` (220 lines: `load_codeowners`, `parse_codeowners`, `glob_to_regex`,
`get_owners_for_path`, `requires_human_approval`, `check_pr_files`) and
`scripts/automation/lib/codeowners.py` (142 lines: `CodeownersEntry`, `_parse_codeowners`,
`_fnmatch_codeowners`, `find_owners`, `actor_is_codeowner`). They implement overlapping CODEOWNERS
parsing with different glob engines (`re` vs `fnmatch`) and different public surfaces. The
preliminary document names only the first. Exposing a CLI over one of them without resolving which is
authoritative would mint a *third* answer to "who owns this path" into the allowlist. Escalated as
**Q7**.

**VF-4 — CORRECTS the preliminary document's G8/G9 premise: the audit helper already has a CLI.**
`scripts/oversight/lib/audit_log.py` has `_main`/`_usage` (`:195`, `:206`) exposing
`python3 -m scripts.oversight.lib.audit_log write [root] [--ts TS]` and `... read [root]`. So G8/G9
are **not** "no CLI exists." The real, narrower defects are three, and all three are shape defects:
1. `write` takes the event JSON on **stdin** — so every call site must build a pipe or a heredoc,
   both categorically unallowlistable. A `--json-file <path>` argv form is what is missing.
2. `read` emits the entire stream unfiltered — so every call site appends `| grep -F …`, which is a
   compound command. Server-side filtering (`--event`, `--match`) is what is missing.
3. The Bash facade `scripts/oversight/lib/audit_log.sh` is documented in its own header as a
   **"sourced library, NOT an executable entry point."** `source` of a path the model composes is
   categorically unallowlistable. A non-sourced entry point is what is missing.
This correction matters for §3.3: the audit work is a *re-shaping* of an existing surface, not a
greenfield build, which lowers its cost and strengthens the case for sequencing it first.

**VF-5 — CONFIRMED, and it is the sharpest instance in the system.**
`bootstrap/overseer-cron-prompt.md:38` instructs, verbatim:
`(source scripts/oversight/lib/audit_log.sh) run audit_read_stream | grep -F '"event":"pr-merged-without-review"' | grep -F "\"pr\":<n>"`.
That is a `source` of a runtime-named file **and** a two-stage pipe **and** a `<n>` placeholder the
model must substitute — three independent unallowlistable constructs in one mandated instruction,
guarding an idempotency check whose failure mode (#849 class) is duplicate issue-filing. Under the
sandbox this instruction cannot execute at all, and its denial is silent.

**VF-6 — CONFIRMED.** `bootstrap/overseer-cron-prompt.md:30` contains the literal
`for pr in $(gh api "repos/thurlow-research/HumanOversightSystem/pulls?state=closed&…" …)` loop the
preliminary document reports as G7. A loop plus command substitution; unallowlistable by
construction.

**VF-7 — CONFIRMED.** `bootstrap/worker-cron-prompt.md:101` contains the literal
`--jq "$(cat scripts/automation/lib/next_candidates.jq)"` the preliminary document reports as G11.

**VF-8 — CORRECTS the preliminary document's §7 open note on `release_artifact_logic.py`: it
partially covers, and the two residuals are the load-bearing parts.** The module *does* have a full
`argparse` CLI (`main`, `:570`; `validate` subcommand at `:574-598`; `--repo-root`, `--manifest`,
`--version`, `--log-to`). But:
1. Its own docstring states the design constraint under "PURITY": *"validate_release_artifacts() does
   file I/O … but NO subprocess, network, or git calls."* It therefore validates the **working tree**,
   not artifacts **as committed on `origin/main`**. The overseer's #695 need includes the
   `git show origin/main:…` reads precisely because the working tree is not the reviewed state. That
   part is **not** covered and cannot be, without breaking the module's stated purity contract.
2. `cut_release.sh` invokes it as `--version $VERSION` — a caller-supplied value. Under §4.6 FR-6.2
   (self-deriving context) that is a defect for any agent-issued invocation.
So the preliminary document's suggestion ("if yes, the cron prompt should invoke it by name") must be
answered "no, not as-is": a git-reading adapter is required, and it must live outside the pure module.

**VF-9 — CORRECTS the preliminary document's §3 "already covered" table: `check_pr_reviewed.sh` is
mis-classified.** The script exists and is well-built, but its interface is
`check_pr_reviewed.sh <pr#> <head_sha> [root]` — positional, with `head_sha` caller-supplied. The
overseer's own instruction for obtaining that value is
`bootstrap/overseer-cron-prompt.md:54`: *"fetch its current head SHA (`gh api repos/{o}/{r}/pulls/<n> --jq .head.sha`)"*.
So the "covered" script is only reachable through an uncovered raw API read plus a substitution. It
belongs in the gap inventory (needs a self-deriving `--pr <N>` form), **not** in the covered list.
This is the general pattern the preliminary document's §3 table may hide elsewhere: *a script
existing is not the same as a script being invocable with literal arguments.* **FR-9.1** makes
re-auditing the whole §3 table against that stricter test an explicit deliverable.
*(Minor, non-blocking doc drift found alongside: `check_pr_reviewed.sh`'s header cites
"`audit_predicate.py`'s CLI convention"; `scripts/oversight/audit_predicate.py` does not exist on
`origin/main`.)*

**VF-10 — CONFIRMED, and it is the largest single cluster.** `scripts/automation/lib/merge_authority.py`
is 1,134 lines with **zero** `__main__` blocks. All nine entry points named in #1357's ruling are
present and CLI-less: `has_human_approval` (`:63`), `detect_human_hold_directive` (`:116`),
`detect_server_side_gate` (`:226`), `touches_protected_surface` (`:381`), `decide_merge_authority`
(`:471`), `open_draft_pr` (`:713`), `route_embargo` (`:745`), `check_register_completeness` (`:887`),
`bounce_count` (`:977`), `record_pr_bounce` (`:1059`). Note for W5: `_convert_pr_to_draft` (`:1021`)
exists inside the module, so the draft conversion **is** already on the Python path — the preliminary
document's W5 "verify whether the Python path already performs this" is answered *yes*, and W5 should
be dropped as a separate wrapper unless a shell-side caller is found.

**VF-11 — CORRECTS an assumption in the preliminary document's §4: `github.py` does not cover the PR
read namespace, so R1–R8 need new library functions, not just a CLI shim.**
`scripts/automation/lib/github.py` exposes `get_ref` (`:141`), `get_branch` (`:151`), `list_pulls`
(`:159`), `list_issue_comments` (`:182`), `get_branch_protection` (`:209`), `get_repo` (`:223`),
`post_comment` (`:228`) — and nothing else. There is **no** single-PR detail getter, no reviews
lister, no changed-files lister, no issue-events lister, no labels lister, and no commit getter. The
preliminary document's instruction to "build on `github.py` (retry/backoff already implemented — do
not re-implement, #1213)" is correct as *direction* but understates the work: R1, R2, R3, R5, R6, R7
and R8 all require new functions in that module. Only R4 (open-PR list) is served today.

**VF-12 — CONFIRMED.** `scripts/framework/gen_sandbox_config.py` lists `KNOWN_ROLES = ("human",
"worker", "overseer")` (`:129`) but returns `EXIT_UNSUPPORTED_ROLE = 3` (`:164`, `:968`) for worker
and overseer, naming #1146/FR-5 as the reason (`:56`, `:69`, `:187`). The generator is the natural
completion gate for this issue (FR-8).

**VF-13 — CONFIRMED.** `bin/hos-cron:374-423` defines `_sync_audit_logs`: fetches `audit-log` (falling
back to `main`), builds a **detached worktree**, and pushes `HEAD:refs/heads/audit-log`, warning and
continuing on failure (`:421-423`). Invoked once, at `:2132`. This matches #1538's description of the
mechanism that "already basically exists" and is the right shape.

**VF-14 — Milestone reality confirms the ordering #1357 demands.** #1542, #1357, #1538, #1216, #1536,
#1359 and #1244 are all **v0.7.0 — Quality**. #1146 and #1053 are **v0.7.4 — Sandboxing &
Isolation**. #1360 ("invert the driver") is **v0.7.10**. So the sequence #1357's 2026-08-13 comment
argues for — *build the invocable surfaces first, sandbox second* — is already encoded in the
milestones rather than merely asserted, and #1360 lands well after this work rather than before it.
This is decisive for §3.4.

**VF-15 — Documentation-coherence scope, measured.** Raw `gh api` occurrences: `worker.md` 4,
`overseer.md` 4, `worker-cron-prompt.md` 3, `overseer-cron-prompt.md` 4 — **15 sites**. Explicit
"no wrapper …yet/covers" annotations: `overseer.md:449`, `:659`, `:693`, `:696`, `:697`;
`worker.md:327` — **6 sites**. Plus `overseer.md:726`, which tells the overseer that the one
construction it could otherwise attempt (`python3 -c`) is banned. FR-7 is bounded by these counts.

---

## 1. Context

Both autonomous roles run today with **no permission gate**: `bin/hos-cron` launches them with
`--permission-mode bypassPermissions`, and the interactive launchers use
`--dangerously-skip-permissions` (`docs/SANDBOX-POLICY.md` §2). #1146/#1053 will remove that.

The failure mode being designed against is **silent denial**, not refusal. In a headless
`claude --print` session there is no prompt UI: an unallowlistable command is denied outright, the
denial is reported to the model, and the cycle continues **having skipped that step** — exit 0, no
hang (measured 2026-08-01, Test B, #1146). A cycle that skipped a control looks exactly like a cycle
that passed it.

A command is allowlistable only if its full text is statically matchable. Command substitution,
heredocs, `$VAR` expansion in arguments, loops, backslash continuations, `source` of a runtime-named
file, and `&&`/`;` chaining all defeat matching. **Therefore every action either role takes in
autonomous mode must be expressible as a single invocation of a committed script with literal
arguments** — or it will silently not happen.

This is a *prerequisite*, not a co-requisite. Sandboxing before the surfaces exist converts a wrong
answer into a missing one (#1357's 2026-08-13 analysis), and both are invisible in the artifacts.

---

## 2. Scope

### 2.1 In scope

Every Bash-tool command the `worker` or `overseer` issues in AUTONOMOUS mode, including commands
their own CORE regions and cron prompts currently instruct them to issue raw — **minus** the two
scope carve-outs settled in §3.

### 2.2 Out of scope

- `bin/hos-cron` itself. It is a cron shell script running *outside* the Claude session; permission
  rules never apply to it. Its pre-computed context (NEW WORK directive, actionable-PR preamble,
  candidate lists, release-request lists) is an existing mitigation the agents should lean on harder,
  not re-derive. Note the exception: FR-7 still applies to the *prompt text* `hos-cron` injects.
- Interactive-mode behaviour, except as a free consequence (the same scripts remove prompt friction
  for the Human role; no separate work).
- The sandbox policy's filesystem and network boundaries. This issue covers the **Bash allowlist**
  only; path scoping is #1146's.
- The specialist-subagent command surface (see NG-4).

### 2.3 Explicitly deferred to `architect`

Named here so `technical-design` does not treat this document's silence as permission:
CLI granularity (§3.2 / **Q1**), read-wrapper policy (**Q4**), library-versus-CLI ownership split
(**Q3**), one-script-versus-two for the issue/PR namespaces (**Q5**), and language choice per script.

---

## 3. Resolution of the overlap with #1357 and #1538

This section is the reason this document exists. The preliminary document was written on 2026-09-10
and its gap inventory overlaps, without acknowledging it, with two issues ruled by the human **the
same day, hours later**. Leaving the overlap noted-but-unresolved would produce three teams building
the same surface.

### 3.1 The overlap, stated precisely

| Preliminary-doc item | Overlapping issue | Nature of overlap |
|---|---|---|
| §6 P8–P13 (`merge_authority.py`: `detect_server_side_gate`, `check_register_completeness`, `decide_merge_authority`, `detect_human_hold_directive`, `touches_protected_surface`/`has_human_approval`, `record_pr_bounce`) | **#1357** | **Identical.** Same functions, same defect, same fix family. #1357 additionally names `bounce_count` and `route_embargo`, which the preliminary document omits. |
| §6 P14 (`codeowners.py:check_pr_files`) | **#1357** (adjacent) | Same class; #1357's ruling does not name it. VF-2/VF-3 make it messier than either document assumes. |
| §7 G8 (`audit_query`) and G9 (`audit_append`) | **#1538** | **Identical in target, different in mechanism.** See §3.3. |
| §8 cross-cutting rule 8 (prompt/agent-file updates) | **#1357** point 2, **#1538** scope | Both issues already carry a share of the same edits to the same four documents. |

### 3.2 #1357 — KEEP, SEQUENCE FIRST, and bind its granularity (escalated as **Q1**)

**Recommendation: #1357 stays open as an independent, separately-tracked issue; it is sequenced
*before* #1542; and #1542 formally excludes P8–P14 from its own delivery inventory, inheriting them
as a dependency.**

Why not supersede-and-close it into #1542: #1357 carries four ruling comments and a live-risk
assessment that no other issue reproduces, including the finding (2026-08-14, overseer bot comment)
that `_dep_ceiling_check_present` (`merge_authority.py:187`) is a hardcoded `return False` stub, so
`decide_merge_authority` currently returns `PROPOSE_ONLY` for *every* PR — meaning every historical
`AUTO_MERGE` disposition was narration that the real code contradicts. That is a live correctness
defect in the merge-authority path with a mitigation posture already recorded on the issue. Folding
it into a broader script-coverage issue would bury it, and #1542 is a v0.7.0 *enabling* issue whose
failure mode is friction, whereas #1357's is an unfired control. They should not share a fate.

Why sequence #1357 first rather than after: #1357's own 2026-08-13 comment establishes the ordering
argument, VF-14 shows the milestones already encode it, and the practical reason is that
`overseer_decide` is the single largest consumer of the PR-read namespace this issue delivers — but
it is a consumer with a *known, enumerable* read list, so it can be built against a small purpose-
built read layer without waiting for the full R1–R8 CLI (see **Q3**).

**The granularity conflict — and why it needs a human.** #1357 contains two rulings that do not
agree on shape:

- **2026-08-13** (§"Design note — prefer one decision surface over nine wrappers"): *"Nine
  per-function wrappers would mirror the library's internal shape into the shell and leave the agent
  responsible for sequencing them correctly — which is the same 'agent re-derives the control flow'
  failure in a new form."* Proposes one `bootstrap/pr_decide.sh`-style entry point emitting a
  structured JSON verdict.
- **2026-09-10** (point 1 of the ruling): *"Every entry point above needs a real, invocable,
  statically-allowlistable CLI wrapper."*

Read literally, the second mandates nine wrappers and re-creates the failure the first warns about.
The preliminary document's §6 recommendation (one `overseer_decide.py` performing the full
deterministic pre-decision pipeline internally) is the *same shape* as the 2026-08-13 note.

**PM recommendation:** the 2026-08-13 design note governs. Read the 2026-09-10 clause as *"every
entry point must be reachable through a real, invocable, statically-allowlistable surface"* — a
requirement on **reachability**, which one decision CLI satisfies for the read/derive functions —
rather than as a requirement on **arity**. Concretely:

- One **read-only decision surface** covering `detect_server_side_gate`, `check_register_completeness`,
  `detect_human_hold_directive`, `touches_protected_surface`, `has_human_approval`, `bounce_count`,
  `route_embargo` and `decide_merge_authority`, emitting one JSON decision record with per-gate
  evidence. The agent *acts on* the verdict and never re-derives it.
- Separate, narrow wrappers **only for operations that mutate state**: `record_pr_bounce`, and the
  §4.2 PR-write operations. Least privilege per script; one operation per wrapper.

**This is a `structural` change to a same-day human ruling** — it narrows the literal wording of a
recorded decision. Per this role's escalation rules it is **not** applied here and MUST NOT be bound
by `architect` until the human rules it. It is **Q1**.

**Boundary, if Q1 is approved as recommended:**

| Deliverable | Owner |
|---|---|
| The overseer decision surface (P8–P13 + `bounce_count`, `route_embargo`) | **#1357** |
| `record_pr_bounce` mutating wrapper | **#1357** |
| The `check_pr_files` / CODEOWNERS surface (P14) and the VF-3 duplicate-module resolution | **#1357** if the decision surface calls it internally; otherwise **#1542**. Escalated as **Q7**. |
| PR-read library functions + read CLI (R1–R8) | **#1542** — see **Q3** for the split |
| PR-write wrappers (W1–W4) | **#1542** |
| Worker-side lifecycle CLIs (P1–P7) | **#1542** |
| Compound git/release operations (G1–G7, G10–G13) | **#1542** |
| Cross-cutting invariants, doc coherence, allowlist artifact | **#1542** |

### 3.3 #1538 — KEEP INDEPENDENT, SEQUENCE FIRST, and add one constraint (**Q2**)

**Recommendation: #1538 stays open and independent; it is sequenced *before* #1542; #1542 deletes
G8 (`audit_query`) and G9 (`audit_append`) from its own inventory and restates them as a
*consumer constraint* on #1538's deliverable.**

Three reasons this is not a merge:

1. **A human process ruling on #1538 (2026-09-10) explicitly says "Skip pm-agent."** The requirements
   are stated directly in its body and the human ruled that nothing there needs elicitation. Re-
   opening #1538's requirements inside a `pm-agent` document would contradict that ruling. This
   document therefore does not restate, refine, or re-scope #1538's mechanism; it states only what
   #1542 needs *from* it.
2. **#1538 is a behavioural change, not a CLI-shape change.** Its core is that logging becomes a
   forced side effect of the doing-scripts (`run_panel.sh`, `run_second_review.sh`, the merge action,
   the PR-open action, `run_validators.sh`), plus a permanent segmentation of the `audit-log` ref
   from `main`. G8/G9 are only the sliver of that which #1542 cares about. Absorbing #1538 into #1542
   would drag a supersession chain (#1157, #1095's backlog recovery, #1517's retargeting) into a
   script-coverage issue that has no business owning it.
3. **#1538 largely dissolves #1542's audit-write problem rather than sharing it.** This is the
   important structural point and it is not stated on either issue: *if logging is a side effect of
   scripts the agent must already call, the agent never issues an audit-write command at all* — so
   **G9 disappears from the sandbox command surface entirely**, rather than needing a wrapper. That
   is a strictly better outcome than anything #1542 could have specified, and it is an argument for
   sequencing #1538 first.

**The residual, which #1538's body does not cover — and the one constraint #1542 must place on it.**
The *read* side does not dissolve the same way. Audit **reads** are agent-issued idempotency
prechecks (the #849 class: `human-authorized-merge`, `pr-merged-without-review`,
`release-gate-validation`, and the worker's NG3b checks), and no doing-script can perform them as a
side effect because they must run *before* the agent decides whether to act. VF-5 shows the current
mandated read form uses three separate unallowlistable constructs. So:

> **CR-1 (constraint on #1538, for human confirmation as Q2).** #1538's shared audit surface must be
> invocable by an agent as a **single command with literal arguments** for both directions:
> - **write** must accept the event as a file path argument (VF-4 defect 1 — stdin forces a pipe);
> - **read** must accept server-side filter arguments so no `| grep` is required (VF-4 defect 2);
> - neither may require `source`-ing a shell library (VF-4 defect 3).
>
> This is an *additional acceptance criterion* on #1538, not a re-scope of it, and it is cheap:
> VF-4 shows the CLI already exists and needs flag-shape work, not a greenfield build.

If the human declines CR-1 (i.e. #1538 ships without the argv-shape constraint), then #1542 must
re-absorb G8 as a wrapper over #1538's surface, and this document's FR-5 grows by one item. That
fork is **Q2**.

**One defect to hand to #1538 regardless (informational, not a scope change):** VF-1 —
`cycle_log.py:log_event` hardcodes `"role": "worker"` into every record. A shared both-roles logging
path cannot carry that. Recording it here so it is not rediscovered during implementation.

### 3.4 Other issues in the same family — dispositions

| Issue | Milestone | Disposition |
|---|---|---|
| **#1359** — enshrine "use the code, don't roll it yourself" in `AGENTS.md` | v0.7.0 | **Independent, no boundary needed.** It is the governance statement of the principle these issues instantiate. No deliverable overlap. |
| **#1360** — invert the driver: deterministic code owns the workflow | v0.7.10 | **Independent and downstream.** A 2026-09-06 comment on #1357 proposed folding #1357 into #1360's design pass; the 2026-09-10 ruling superseded that by dispatching #1357 on its own, and VF-14 shows #1360 is three milestones later. **Recommendation:** #1360's design pass should treat the surfaces #1357/#1542 deliver as its substrate rather than redesigning them, and #1542 should build them CI-invocable and non-interactive so that inversion is a relocation, not a rewrite (FR-6.9). Flagged for human confirmation as **Q11**. |
| **#1216** — run in CI what can run in CI | v0.7.0 | **Overlapping consumer, not a competing producer.** Several overseer checks are slated to move to CI. **Requirement:** every script this issue produces must be invocable from CI on day one — no interactive prompts, no dependence on an agent session, no reliance on a mint/revoke flow that only exists in a cron cycle. FR-6.9. |
| **#1536** — retire validation-stamp attestation; overseer runs framework-validation itself | v0.7.0 | **Adjacent producer.** It creates a *new* overseer-issued execution the sandbox must cover. **Requirement:** whatever #1536 has the overseer run must satisfy this document's FR-6 invariants, or it will ship a new unallowlistable call. Flagged as **Q12**. |
| **#1146 / #1053** — sandbox the roles | v0.7.4 | **Downstream consumers.** This issue is their prerequisite. FR-8 is the handoff artifact. |
| **#1244** — no CI workflow runs the test suite | v0.7.0 | Independent; interacts only via FR-6.7 (each script lands with tests). |

### 3.5 Summary of the recommended dispositions

- **#1357:** kept open, independent, **sequenced before #1542**, scope narrowed to the overseer
  decision chain, granularity bound to *one decision surface + narrow mutating wrappers* — **pending
  human approval of Q1**, because that narrows a same-day ruling's literal wording.
- **#1538:** kept open, independent, **sequenced before #1542**, no re-scope, plus one added
  acceptance criterion **CR-1** on argv shape — **pending human confirmation of Q2**.
- **#1542 (this issue):** **deletes** P8–P14 and G8/G9 from its own inventory, and gains an explicit
  dependency edge on both. What remains is the PR-namespace read/write layer, the worker-side
  lifecycle CLIs, the compound git/release operations, the cross-cutting invariants, the
  documentation-coherence sweep, and the allowlist artifact.
- **Nothing is closed as superseded.** No issue in this family is a duplicate of another; each has
  a distinct failure mode and a distinct owner surface.

---

## 4. Functional requirements

Requirement IDs are stable. The `R#`/`W#`/`P#`/`G#` codes in parentheses are the preliminary
document's, retained for traceability.

### 4.1 FR-1 — PR-namespace read coverage

The autonomous roles must be able to obtain each of the following without command substitution,
`--jq` expressions on the command line, or pipes. Per **VF-11**, each needs a *library* function as
well as an invocable surface.

| ID | Required answer | Consumers |
|---|---|---|
| FR-1.1 (R1) | For a given PR: head SHA, `mergeable_state`, draft flag, labels, author, requested reviewers, milestone | worker Step 1 + conflict path; overseer steps 3, 5; `check_pr_reviewed` (VF-9) |
| FR-1.2 (R2) | For a given PR: the review list with state, `commit_id`, reviewer login and review id | worker CHANGES_REQUESTED path; overseer human-approval checks (#589/#741/#1251), batch-merge re-check |
| FR-1.3 (R3) | For a given PR: changed-file list and commit count | overseer size check §3a; worker PR-size self-check |
| FR-1.4 (R4) | Open PRs, optionally filtered by author | worker Step 1 fallback; overseer preamble fallback (partially served by `github.py:list_pulls`) |
| FR-1.5 (R5) | Recently-merged PRs **with `merged_by` resolved per-PR** (the list endpoint always returns null, #758), windowed | overseer Step 0 merge audit |
| FR-1.6 (R6) | Issue events (`assigned`/`labeled`/`unlabeled`) with actor/assignee/assigner logins and timestamps | worker NG3b R5 three-signal verification; overseer C3 |
| FR-1.7 (R7) | Repo label list | overseer label-convention detection |
| FR-1.8 (R8) | Committed-at timestamp for a given commit | overseer #902 hold-directive detection |

**FR-1.9 — in-wrapper matching.** Comment reads are routinely followed by a literal-marker grep
(`<!-- hos-worker-merge-block -->`, `<!-- hos-ng3b-awaiting -->`, `Authorization required:` + SHA).
Piping wrapper output into `grep` re-introduces a compound command. The match must be performable
inside the wrapper (a `--contains <literal>` / `--author <login>` capability on the existing
comments read).

**FR-1.10 — output shape.** Results emitted as stable structured data on stdout, so the model
consumes the result directly rather than filtering it in shell.

### 4.2 FR-2 — PR-namespace write coverage (overseer)

Each is currently documented as a raw API call (VF-15: `overseer.md:449`, `:696`, `:697`).

| ID | Operation | Notes |
|---|---|---|
| FR-2.1 (W1) | Approve a PR with a canonical body | Overseer-only. **Should require a decision artifact as input** so the wrapper can refuse an approval with no recorded matrix decision — this is the mechanism that makes #1357's "executed, not narrated" checkable after the fact. Depends on #1357's decision-record format; escalated as **Q6**. |
| FR-2.2 (W2) | Merge a PR (squash) | Overseer-only. Must confirm the merge result and fail loud on partial failure. Requirement: **re-read approvals immediately before merging** inside the wrapper (the contract's "never use a cached result" becomes enforceable here). The §6b serialization protocol stays in the orchestration layer. |
| FR-2.3 (W3) | Request a reviewer | Idempotent by API semantics; safe to run every cycle. |
| FR-2.4 (W4) | Dismiss a review with a reason | Needs a review id from FR-1.2. |
| ~~W5~~ | Convert PR to draft | **Dropped** per VF-10 — `_convert_pr_to_draft` is already on the Python path inside `record_pr_bounce`. Reinstate only if `technical-design` finds a shell-side caller. |

**FR-2.5 — least privilege.** One operation per wrapper, identity guard inside the script, free text
only via a file argument, loud stderr, non-zero exit on partial failure. The point is that the
allowlist rule can name a specific script rather than a general API capability; a rule permitting
arbitrary authenticated API calls would forfeit the entire control.

### 4.3 FR-3 — Worker-side lifecycle logic must be invocable

Per **VF-1**, none of these have an entry point today. Unlike the overseer decision chain, these are
genuinely discrete steps in a lifecycle the agent legitimately sequences, so per-operation surfaces
are appropriate here (this is the asymmetry the preliminary document identified and this document
endorses).

| ID | Capability | Worker step |
|---|---|---|
| FR-3.1 (P1) | Correlation/idempotency precheck — has this work already been done? | step 1 |
| FR-3.2 (P2) | Circuit-breaker state: is this task poisoned; record a task failure | step 2 (and overseer step 2) |
| FR-3.3 (P3) | Claim / release / heartbeat on a task | steps 3, 4, 10 |
| FR-3.4 (P4) | Triage a candidate | step 6 |
| FR-3.5 (P5) | Budget estimate and decision | step 7 |
| FR-3.6 (P6) | Emit and parse claim/release envelopes | steps 3, 10 |
| FR-3.7 (P7) | Append a run/cost record to the ledger | terminal |

### 4.4 FR-4 — Compound git, release and readiness operations

G8/G9 are **removed** (→ #1538, §3.3). The remainder:

| ID | Capability | Replaces |
|---|---|---|
| FR-4.1 (G1) | Commit with an enforced trailer set (`Prompt-Artifact`, `AI-Model`, `AI-Risk`, `Supervised-by`), message supplied as a file; refuses on a missing trailer | heredoc / multi-line `git commit -m "$(…)"` — used on **every** worker and coder commit |
| FR-4.2 (G2) | The full §3b validator-artifact ancestry verdict (artifact commit lookup, `head_sha == parent`, ancestor check, PR-scoped staleness diff with exempt paths, schema check) | five chained git commands with substitutions |
| FR-4.3 (G3) | PR readiness with **self-derived** base/head SHAs and cid | `pr_readiness.py`'s five required caller-supplied arguments (VF: `--cid --base-sha --head-sha --step --risk-tier` all `required=True`) |
| FR-4.4 (G4) | Release tier: last tag, semver bump class, PATCH-promotion rule → tier + required-suite list, **self-derived** | `git describe --tags` plus a hand-applied table; and `release_logic.py`'s caller-supplied `--tag` |
| FR-4.5 (G5) | NG3b release authorization status: R1 trigger validation (title/label/state/`Command:` line/R1.5 creator-vs-`BOT_ACCOUNTS`) **and** R5 verification (current-state conditions, authorizing self-assignment event shape, three-signal same-actor check, CODEOWNERS membership, `T_comment` ordering, HEAD binding) → a single verdict plus evidence | the most intricate prose-only protocol in the system; today many raw event reads plus hand evaluation, every cycle |
| FR-4.6 (G6) | Compose the R3/R4 release results comment body (suite results incl. carry-forward restatements, fenced `git log <tag>..HEAD`, `git status --short`, candidate-SHA line, `Command:` line, how-to-authorize block) into a file | agent-composed body from redirected substitution output |
| FR-4.7 (G7) | Recently-merged sweep resolving `merged_by` per PR, windowed | the literal `for … $(gh api …)` loop at `overseer-cron-prompt.md:30` (**VF-6**) |
| FR-4.8 (G10) | Identity assertion: assert the running role is the expected one, non-zero on mismatch | `[ "$HOS_BOT_LOGIN" = "…" ] \|\| exit 1` — `$VAR` expansion, in **both** cron prompts |
| FR-4.9 (G11) | Next-candidate selection using the canonical ordering filter | `--jq "$(cat …/next_candidates.jq)"` at `worker-cron-prompt.md:101` (**VF-7**) |
| FR-4.10 (G12) | Dirty-PR branch rebuild: identify unique commits, branch from current main, cherry-pick, in-place update of the same remote branch | a prose-described multi-step git sequence including a force-push path that bypasses `submit_pr.sh` (the residual gap `CLAUDE.md` § "Submitting a PR" names). **Note:** this one is not merely an allowlisting fix — it closes a known safety gap in the merge-from-base guard. |
| FR-4.11 (G13) | Out-of-scope-commit handling (SPEC-328 Option A): revert on the PR branch, create the follow-up branch from target, cherry-pick | raw `git revert` / `git cherry-pick` / branch dance |
| FR-4.12 (VF-8) | Release-gate deep validation **against committed state** — a git-reading adapter over `release_artifact_logic.py` supplying artifacts as they exist on `origin/main`, with a self-derived version | today the module reads the working tree and takes `--version` from the caller; the `git show origin/main:…` reads have no home |
| FR-4.13 (VF-9) | Self-deriving PR-review idempotency precheck (`--pr <N>`, head SHA derived internally) | `check_pr_reviewed.sh <pr#> <head_sha>` + a raw `gh api … --jq .head.sha` to feed it |

### 4.5 FR-5 — Audit read/write surface

**Delegated to #1538** (§3.3). #1542's requirement on it is **CR-1** only. If **Q2** resolves against
CR-1, FR-5 becomes a #1542 deliverable: a single-invocation audit read with server-side filtering,
built over #1538's shared implementation, never `source`d.

### 4.6 FR-6 — Cross-cutting invariants (every script above)

1. **Single invocation, literal arguments.** Fully drivable as one command with literal values;
   anything long goes in a file argument. No script may *require* the caller to compose substitution,
   pipes, or environment-variable arguments.
2. **Self-deriving context.** Wherever today's usage forces the caller to substitute a value the repo
   already knows (HEAD SHA, base SHA, last tag, repo slug, milestone number, cid), the script derives
   it internally. Per VF-8, VF-9 and FR-4.3 this is the single highest-yield rule in the document: it
   is the root fix for most substitution patterns, and it is where existing "covered" scripts fail.
3. **Identity guard inside the wrapper,** never in the caller's shell.
4. **Structured output to stdout, diagnostics to stderr, stderr never suppressed** (#1533 /
   `check_pr_reviewed.sh` convention). Distinct exit codes for distinct failures; a reporter exits 0
   having answered, and the caller decides what the answer means.
5. **No secrets on stdout or argv.** Token flows stay inside the established mint/revoke scripts
   (#1086, #734).
6. **Idempotent, or shipped with its read-side precheck in the same script.** Any write a rolling
   window can re-trigger (the #849 class) must not depend on the agent remembering a separate check.
7. **Tests, and index regeneration, land with the script.**
8. **Prompt and agent-file updates land in the same change.** VF-15 bounds this: 15 raw `gh api`
   sites and 6 "no wrapper yet" annotations across `worker.md`, `overseer.md` and the two cron
   prompts. A script that lands without replacing its raw form leaves the agents emitting the
   unallowlistable version — and, per #1357's 2026-08-13 finding, *prose describing a future control
   changes behaviour the moment it is written*, so the inverse is equally true: prose describing a
   retired raw form keeps that form alive.
9. **CI-invocable from day one** (#1216, #1360): non-interactive, no dependence on an agent session
   or a cron-cycle-only credential flow, so later migration to CI is a relocation rather than a
   rewrite.
10. **Fail safely.** Scripts fail loud and exit; agents report and stop. No script may paper over a
    denial by retrying an alternate path.

### 4.7 FR-7 — Documentation coherence

The four documents that drive autonomous behaviour (`worker.md`, `overseer.md`,
`worker-cron-prompt.md`, `overseer-cron-prompt.md`) plus `CLAUDE.md`'s canonical entry-point table and
the sandbox policy document must, at completion, contain **zero** instructions to issue an
unallowlistable construct. Bounded by VF-15's counts. Note that `overseer.md:726` (the `python3 -c`
prohibition) should *remain* — it is correct — but it must no longer be the only thing standing
between the agent and an unfired control.

### 4.8 FR-8 — The allowlist artifact (the completion gate)

The end state is a generated worker/overseer sandbox policy — `gen_sandbox_config.py` accepting
`--role worker` and `--role overseer` instead of returning `EXIT_UNSUPPORTED_ROLE` (**VF-12**) —
whose Bash allowlist consists essentially of: the wrapper scripts by literal path, the
test/validator/gate runners, and a short enumerated list of read-only git commands.

**That rule set must be enumerated as an explicit artifact and reviewed as such.** It is the
document that says what the autonomous roles are permitted to do, and it should read like a
capability list, not like an accident of what happened to be needed.

**Candidate raw commands that may stay raw** (`architect` to confirm the exact set): `git status
--short`, `git fetch origin`, `git log …`, `git diff --stat …`, `git rev-parse …` — **as standalone
reads whose output the model consumes directly**, never as substitutions inside another command.
That distinction is the whole of the rule and must be stated explicitly in the artifact, because it
is the one place where the same text is safe in one position and unallowlistable in another.

### 4.9 FR-9 — Acceptance criteria

- **FR-9.1 — Re-audit the "already covered" list against the stricter test.** VF-9 showed at least
  one script classified as covered that is unreachable without substitution. Every entry in the
  preliminary document's §3 table must be re-checked against *"can an agent invoke this with literal
  arguments only?"*, not merely *"does this script exist?"* Findings become additional FR-4 items.
- **FR-9.2 — A detector, not an attestation.** Completion is demonstrated by a check that *executes*
  — scanning the four behaviour-driving documents for unallowlistable constructs (substitution,
  heredoc, `$VAR` in an argument, `source`, `for`/`while`, pipes into `grep`, `&&`-chaining, bare
  `gh api`) and failing on a hit. Per #1359 and #1357, a completion claim asserted in prose is
  exactly the failure class this issue exists to remove; the acceptance criterion must not itself be
  a narrated control. Recommended to run in CI (FR-6.9).
- **FR-9.3 — At least one end-to-end exercise per role** proving that a full autonomous cycle's
  command sequence is expressible under the FR-8 rule set. Escalated as **Q10** (whether this is a
  dry-run harness or a live shadowed cycle is `architect`'s call).
- **FR-9.4 — `gen_sandbox_config.py` accepts both roles** and emits the FR-8 artifact.
- **FR-9.5 — No new unallowlistable construct is introduced** by #1536, #1216 or #1538 work landing
  in parallel (see **Q12**).

---

## 5. Non-goals

- **NG-1 — This issue does not sandbox anything.** It removes the reasons a sandbox would break the
  roles. Turning the sandbox on is #1146/#1053, v0.7.4.
- **NG-2 — Not a rewrite of the decision logic.** The libraries are, per #1357's ruling, correct and
  executable; this is about reachability. The one exception is the `_dep_ceiling_check_present` stub
  (VF-10), which belongs to #1357 and is called out there.
- **NG-3 — Not a re-litigation of #1538's mechanism.** A human ruled its requirements settled and
  skipped `pm-agent`. §3.3 adds one constraint and nothing else.
- **NG-4 — The specialist-subagent command surface is deferred.** `coder`, the eight reviewers,
  `unit-test`, `system-test` and `risk-assessor` run in the same sandboxed session and need the same
  treatment. Their surface is mostly already script-shaped (test runners, validators, gates), with
  two known exceptions: `coder`'s git usage hits FR-4.1, and `risk-assessor` passes changed-file lists
  to validators in a form nobody has checked. **A per-agent audit pass is required before #1146 ships**
  — recommended as its own v0.7.0 issue rather than as silent scope here. Escalated as **Q8**.
- **NG-5 — No new GitHub App identity, no gate exception, no change to any human-approval gate.**
  Nothing in this document loosens an approval requirement; several items (FR-2.1, FR-2.2) tighten
  one.
- **NG-6 — Not a performance or cost optimisation.** Consolidating calls into scripts may reduce
  token usage; that is a side effect and must not drive granularity decisions.

---

## 6. Product decisions escalated to the human

Ordered by consequence. **Q1** and **Q2** are blocking for `architect`; the rest may be ruled during
the architecture pass but must not be decided silently.

**Q1 — [STRUCTURAL, BLOCKING] Does the 2026-08-13 "one decision surface" note govern over the
2026-09-10 "every entry point needs a wrapper" wording on #1357?**
Recommendation: yes — one read-only decision surface for the derive/decide functions, narrow wrappers
only for mutating operations (§3.2). This narrows the literal wording of a same-day ruling, so it is
not applied here. If the human prefers the literal reading (one wrapper per function), say so and
`architect` builds nine; this document's §3.2 boundary table and FR-2.1's decision-artifact
requirement both change as a result.

**Q2 — [BLOCKING] Is CR-1 accepted as an added acceptance criterion on #1538?**
That #1538's shared audit surface must be invocable as a single command with literal arguments — file
argument for write, server-side filters for read, no `source`. If declined, #1542 re-absorbs the
audit-read wrapper (FR-5) and its scope grows.

**Q3 — Who owns the PR-read *library* functions (VF-11), given #1357 is sequenced first?**
`overseer_decide` needs single-PR detail, reviews and changed files internally, and `github.py`
provides none of them. Options: (a) #1357 adds the functions it needs, #1542 adds the rest plus the
CLI; (b) #1542's library layer is pulled forward and #1357 depends on it; (c) the library layer
becomes its own small issue that both depend on. Recommendation: **(a)** — it keeps #1357 unblocked
and avoids a three-way dependency, at the cost of #1542 later extending rather than authoring.

**Q4 — Read-wrapper policy: named operations, or a narrowly-scoped generic GET?**
The repo philosophy (#1213, "one invocation site") favours named operations, and a generic GET
wrapper is close to an arbitrary-authenticated-API allowlist rule. Recommendation: **named operations
only**, accepting the long tail as friction. Flagging it because the long tail is real and the cost
lands on whoever hits an unnamed read mid-cycle.

**Q5 — One read script for both namespaces, or separate issue and PR scripts?**
`query_issues.sh` exists and is well-established; the PR namespace is 8 new operations. Either
extending it or adding a sibling satisfies the requirements. No PM preference; noted so `architect`
rules it rather than inheriting it.

**Q6 — Should the approve and merge wrappers (FR-2.1/FR-2.2) *refuse* to act without a decision
record from #1357's decision surface?**
Recommendation: **yes.** It converts "the overseer executed the matrix" from an attestation into a
precondition, which is the strongest available answer to #1357's failure mode. Escalated rather than
asserted because it is a **new blocking condition on the merge path** — structural by this role's
own test, and it introduces a hard dependency from #1542 onto #1357's artifact format.

**Q7 — Which `codeowners` module is authoritative (VF-3), and does the CODEOWNERS gate (P14) belong
to #1357 or #1542?**
Two modules with different glob engines exist. Exposing a CLI over one without retiring or
subordinating the other adds a third answer to "who owns this path" — and CODEOWNERS drives the
human-approval gate, so a divergence here is a governance defect, not a tidiness one. Recommendation:
resolve the duplication *before* either gets a CLI, and assign P14 to whichever issue owns the
protected-surface gate.

**Q8 — Is the specialist-subagent audit (NG-4) filed as its own v0.7.0 issue now?**
Recommendation: **yes, now.** It is a known prerequisite of #1146 and it is the kind of scope that
otherwise surfaces during the sandbox rollout as a silent skip.

**Q9 — Does the FR-8 allowlist artifact require human sign-off as a protected surface?**
It is the capability list for two autonomous roles. Recommendation: **yes** — it should be treated as
a protected surface with an explicit human approval on every change, not regenerated silently.
Depends partly on live repository settings this session did not inspect.

**Q10 — What form does FR-9.3's end-to-end proof take?** Dry-run harness replaying a recorded cycle's
command sequence against the rule set, or a live shadowed cycle under the sandbox with denials logged
but non-fatal. The second is stronger evidence and costs a rollout window. No PM preference.

**Q11 — Is #1360 confirmed as downstream of, and building on, these surfaces?**
Recommendation: yes (§3.4). Recorded because a 2026-09-06 comment pointed the other way and was
superseded on 2026-09-10; the supersession should be explicit rather than inferred.

**Q12 — Who enforces FR-9.5 across the parallel v0.7.0 issues?**
#1536 in particular introduces new overseer-issued execution. Some issue must own "no new
unallowlistable construct ships in v0.7.0." Recommendation: this issue owns the detector (FR-9.2) and
the detector runs in CI, so enforcement is mechanical rather than assigned to a reviewer's attention.

---

## Human Review Required

**RISK: MEDIUM**
**CONFIDENCE: HIGH** on the verification findings (§0 — all fifteen re-derived from `origin/main`
`dfa9bf8e`, with the four caveats stated at the top of §0). **MEDIUM** on the §3 dispositions, which
are recommendations about how three human-ruled issues relate and require confirmation rather than
acceptance. **LOW** on completeness of the underlying gap inventory: it inherits the preliminary
document's census of *where* each operation is used, which was spot-checked rather than re-derived
exhaustively, and VF-9 demonstrates that at least one item was mis-classified in the direction of
under-counting. Expect the inventory to grow during `technical-design`, not shrink.

**Change classification: `structural`.**
Three things make it structural rather than additive:
1. **§3.2 / Q1** narrows the literal wording of a human ruling recorded on #1357 on 2026-09-10.
2. **§3.3 / Q2 (CR-1)** adds an acceptance criterion to #1538, an issue on which a human explicitly
   ruled that `pm-agent` be skipped.
3. **Q6** proposes a new blocking precondition on the merge path (approve/merge refuse without a
   decision record) — a new decision point that did not exist before.

None of the three is applied in this document. `architect` may proceed on §4 and §5, and MUST NOT
bind Q1, Q2 or Q6 until the human rules them.

**What is NOT escalated and may be treated as settled:** §0's verification findings, §4.1–§4.4 and
§4.6–§4.9 as *requirements* (their design remains open), §5's non-goals, and the §3.4 dispositions
for #1359, #1216, #1244, #1146 and #1053.

**Human decision needed on:** Q1, Q2, Q6 before `architect` binds anything that depends on them;
Q3–Q5 and Q7–Q12 may be ruled during the architecture pass but must be answered, not inherited.
