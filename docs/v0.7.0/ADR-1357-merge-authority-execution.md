# ADR-1357 — The merge-authority matrix becomes executable: a layered, statically-allowlistable CLI surface, with freshness enforced in code rather than narrated

**Status:** ACCEPTED FOR DESIGN — binds `technical-design`. **Three items are held for the human** (§3): ESC-1 (does the merge wrapper honour the above-ceiling human-approved merge path?), ESC-2 (activating `_dep_ceiling_check_present` changes autonomous-merge throughput — a product-boundary item), ESC-3 (is a retrospective audit of previously-narrated dispositions required?). Everything else below is **BINDING**.
**Date:** 2026-09-11
**Author:** architect
**Inputs:** issue #1357 body and its full comment history — the human's 2026-08-13 *"USE THE CODE"* ruling, the 2026-09-10 executable-not-specification ruling, **Q1** (layered CLI: build both levels), **Q6** (mutations recompute fresh, every invocation), and the 2026-09-10 staleness-scope finalization; my own re-verification against `origin/main` (§0).
**Consumers:** `technical-design` (next), then a `needs-ai` issue to the autonomous `worker`, v0.7.0 milestone.
**Source issues:** #1357 (this), #1356 (bounce events never reach the audit log — resolves substantially as a byproduct), #1359 (the governing principle), #1538 CR-1 (filtered audit reads — a named dependency), #1542 (the broader sandboxed-role script inventory — sequenced after this), #1340 (cross-branch semantics at release time), #1216 (branch-currency is false safety), #1325 (the pre-matrix protected-surface gate this design absorbs).
**Explicitly does NOT re-litigate:** the executable-vs-specification question (ruled), the one-surface-vs-nine-wrappers question (ruled: both), the fresh-vs-cached question (ruled: fresh), the branch-currency question (ruled: `mergeable_state == clean` is the bar).

---

## 0. Verification findings — every load-bearing premise re-checked against `origin/main`

**Provenance of this section.** My local clone's `HEAD` was a stale branch from 2026-08-19 and `origin/main` was itself behind. `git fetch origin` **succeeded** (the task brief's premise that fetch is blocked by EROFS on `.git/FETCH_HEAD` in this clone **no longer holds** — recorded here so the next session does not inherit a false constraint). All citations below are `git show origin/main:<path>` at **`4c91f045` (2026-09-10 23:04 PDT)**, not the working tree. `merge_authority.py` and `contract/OVERSIGHT-CONTRACT.md` happen to be byte-identical between the two; `.claude/agents/overseer.md` and `scripts/oversight/lib/audit_log.py` are **not**, and the `origin/main` versions are the ones read.

### Confirming the claims I was handed

- **VF-1 CONFIRMED, with a precision correction.** `_dep_ceiling_check_present` (`merge_authority.py:187-189`) is still a hardcoded `return False`, and `detect_server_side_gate:237-238` short-circuits to `_PROPOSE_ONLY_DEP` before reading any branch-protection state. **But the secondhand claim that `decide_merge_authority` "returns `PROPOSE_ONLY` for every PR regardless of anything else" is not accurate, and the imprecision matters.** The gate re-check sits at `:668-674`, *after* eleven earlier guards. A PR carrying `needs-human`/`hos-halt`, a prior `HUMAN_REQUIRED`, a pending human reviewer, a hold directive, a release signature, a non-`PROCEED` verdict, an above-ceiling tier, an unapproved security/protected surface, or a self-authorship collision returns **`HUMAN_REQUIRED`** and never reaches the gate. The correct statement is: **`AUTO_MERGE` is unreachable for every PR, and any PR that would otherwise have auto-merged returns `PROPOSE_ONLY` instead.** The design below depends on this precise form (see AD-8), because the fail-safe is doing exactly what it was built to do — the defect is upstream of it.
- **VF-2 CONFIRMED.** `merge_authority.py` has no `__main__`, no `argparse`, no CLI entry point of any kind. Its only non-test importer remains `pr_readiness.py` (for `RiskTier`).
- **VF-3 CONFIRMED and extended.** `scripts/oversight/lib/audit_log.py` does already carry a CLI (`write`/`read`, `:195-248`), and the read side is an unfiltered dump — `read_stream` yields every record in `audit/log/**` and the caller filters. `merge_authority.bounce_count:977-994` is a live instance: it scans the entire trail in Python and counts matches itself.
- **VF-4 CONFIRMED.** `tests/automation/test_merge_authority_detection.py` (14 tests), `test_bounce_gate.py` (20), `test_phase_b.py` (123) — **157 tests** — all import the library directly and mock `github.py`. They test the logic and say nothing about whether anything calls it. `test_merge_authority_detection.py`'s own docstring states the stub "means `detect_server_side_gate` always returns PROPOSE_ONLY for now" — the tests encode the broken state as expected.
- **VF-5 CONFIRMED.** `.claude/agents/overseer.md:7` (the charter line) reads verbatim: *"Never opens branches or PRs; only evaluates and acts on artifacts the worker produced."*

### My own findings — these change the design

- **AF-1 (HIGH — the brief's premise about the contract is wrong).** `contract/OVERSIGHT-CONTRACT.md` contains **no R9.1.1 language at all.** Grepping the `origin/main` copy for `R9`, `9.1`, `cached result`, `decide_merge_authority`, `detect_server_side_gate` and `bounce_count` returns **nothing**; the only hits are three `record_pr_bounce()` mentions in the §6a event catalog (`:429`, `:435`, `:454`), which correctly name it as the *producer* of the `pr-bounced` event. The "R9.1.1 — never use a cached result for a merge decision" text lives in exactly two places: `.claude/agents/overseer.md:277` and `merge_authority.py`'s module docstring (`:5`). **Consequence:** the prose-replacement work in AD-11 is `overseer.md`-centric plus a three-line contract touch-up, not a contract rewrite. Anyone planning this work from the brief alone would have looked for contract text that does not exist.

- **AF-2 (HIGH — the DEP `_dep_ceiling_check_present` waits on has already shipped; the constant it needs is provisioned and read by nothing).** The stub's comment says it returns `False` "until the #152 follow-up status check ships." That check **has shipped**: `.github/workflows/require-tier-ceiling.yml` exists on `origin/main` (*"Overseer tier-ceiling gate"*, `pull_request_target`, trusted-base checkout, re-armed on review submit/dismiss by `rerun-gate-checks.yml` per #1299), backed by `scripts/framework/require_tier_ceiling.py`. More pointedly, `TIER_CEILING_CHECK_NAME="require-tier-ceiling"` is already defined in **three** places (`scripts/framework/machine-accounts.env:50`, `bootstrap/apps.env.template:80`, `bootstrap/hos_setup_partner.sh:176`) and asserted by **two** test files — and is read by **no non-test code anywhere in the repo.** The constant exists for precisely one consumer, `_dep_ceiling_check_present`, and that consumer never reads it. This is a second instance of the same "control that never fires" class the issue is about, sitting *inside* the function the issue is about.

- **AF-3 (HIGH — fixing one stub un-masks a second, permissive one).** `_verify_overseer_review_accepted` (`:216-223`) is a hardcoded `return GateDetectionResult(autonomous_capable=True, reason="Overseer review accepted (CODEOWNER check deferred to pre-merge re-check)")` — it inspects neither `protection` nor `overseer_handle`, and `detect_server_side_gate` never reads `required_pull_request_reviews.require_code_owner_reviews` anywhere else. Today this is invisible because `_dep_ceiling_check_present` short-circuits above it. **The moment AF-2 is fixed, this permissive stub becomes load-bearing**: "server-side gate detected" would then rest on protection-exists + `required_approving_review_count >= 1` + `dismiss_stale_reviews` + overseer-not-in-bypass, with the CODEOWNERS half silently always-true. Failing to notice this would be the classic case of repairing a fail-safe and shipping a fail-open. See AD-8.

- **AF-4 (MEDIUM — the library's defaults disagree with the repo's configuration, in a way a naive CLI would inherit silently).** `decide_merge_authority`'s signature defaults `overseer_ceiling: RiskTier = RiskTier.LOW` (`:485`), while `scripts/framework/machine-accounts.env:46` sets `OVERSEER_CEILING="HIGH"`. `overseer_handle`/`worker_handle` default to literal `hos-overseer-hos[bot]`/`hos-worker-hos[bot]` (`:483-484`), which are wrong for every consumer project. `head_sha` defaults to `None`, which `overseer.md:344-345` already warns "disables SHA filtering entirely — a stale approval from before a later push would then satisfy any of these gates." A CLI that simply forwards user-supplied flags and lets the rest default would: over-escalate on HOS (LOW instead of HIGH), mis-identify the actors on any consumer, and — worst — silently disable stale-approval rejection. See AD-9.

- **AF-5 (MEDIUM — the new wrappers will not reach consumer installs unless the ship-set is changed, and neither do the existing ones).** `bootstrap/hos_install.sh:1886-1894` copies `bootstrap/` files **individually, by name**: only `get_app_token.sh`, `hos_repo_sync.sh`, `validate_setup.sh`, `apps.env.template`, `sync_apps_env.sh`. The declared ship-set `scripts/framework/framework_consumer_files.txt` adds `bootstrap/create_branch.sh`, `bootstrap/lib/*`, `bin/**`, five workflows and eight `scripts/framework/` files — and contains **no** `scripts/automation/**`, **no** `scripts/oversight/check_pr_reviewed.sh`, and none of `post_comment.sh` / `query_issues.sh` / `create_issue.sh` / `edit_issue.sh` / `submit_pr.sh` / `post_review_thread.sh`. So a consumer project receives `overseer.md`, which instructs the overseer to call wrappers that were never installed. This design must not add a seventh uninstalled wrapper to that list. See AD-14.

- **AF-6 (MEDIUM — the runtime prompt already proves the fix's shape works).** `bootstrap/overseer-cron-prompt.md` is 66 lines and mentions `merge_authority` **zero** times. Its Step 1 says, in prose: *"run the full review chain (validators, size check, register completeness, merge-authority matrix)."* That is the single line the entire narration defect hangs from. Three lines earlier, the same prompt contains a **literal, statically-allowlistable command** — `bash scripts/oversight/check_pr_reviewed.sh <pr#> <head_sha>` — with an explicit *"literal first command for each PR"* instruction and a *"never suppress this command's stderr"* rule. #1524 built that wrapper for exactly this defect class. **The one control in that prompt written as an invocation is the one that runs.** This ADR's prose changes should copy that shape verbatim rather than invent one.

- **AF-7 (LOW — one named entry point must NOT get a wrapper).** The 2026-08-13 scope list named `open_draft_pr`; the binding 2026-09-10 list does not. `open_draft_pr` (`:713-742`) has **no caller anywhere** in the repo, and building an invocable surface for it would hand the overseer a tool to perform an action its own charter forbids (VF-5). See AD-12.

### Verification gaps I could not close

- **Live branch-protection state on `thurlow-research/HumanOversightSystem`.** I could not read `GET /repos/{o}/{r}/branches/main/protection` — there is no wrapper for branch-protection reads, and the only unwrapped path (`source <(get_app_token.sh)` + `gh api`) is exactly the unallowlistable construction this ADR exists to eliminate. So whether `require-tier-ceiling` is *currently* in the required-checks list, and whether any bypass actor is configured, is **taken as unknown**, not as given. This directly feeds ESC-2, and it is itself an instance of #1542's inventory gap (a read the agent is told to reason about with no script to perform it).
- **Whether any invocation form other than `python3 -c` was ever used.** The issue body's residual check stands; I did not re-run it. It does not change the design — the absence of any CLI entry point (VF-2) makes every invocation form equally impossible.

### One sequencing note on a superseded comment

The 2026-09-06 comment on #1357 says *"Don't run a separate design pass for this issue; it should be folded into #1360's."* That is **superseded** by the four 2026-09-10 rulings, which dispatch this issue independently, and by the milestones: #1357 is **v0.7.0 — Quality**; #1360 is **v0.7.10 — Governance Enforceability**. This ADR proceeds on the later rulings. #1360's broader "invert the driver" work should treat this design as a landed instance to generalize from, not a competitor.

---

## 1. Context

The merge-authority matrix is the highest-stakes decision point in HOS, and across the entire recoverable audit history it has **never executed**. The overseer read the module, evaluated it mentally, and reported the answer it would produce. The only cycle in which it *was* actually invoked (2026-08-14, PR #1365) returned `PROPOSE_ONLY` — **contradicting** the `AUTO_MERGE` that narration had produced for comparable PRs, including #1341's autonomous merge two days earlier.

The trap was mutually-unsatisfiable instructions: `overseer.md` said *call `record_pr_bounce(...)`*, and `overseer.md:722-729` said the one shell construction that could do so (`python3 -c "..."` with runtime-variable arguments) is unallowlistable. An agent whose only capability is issuing shell commands, told to call a Python function with no shell surface, will narrate — and the narration is indistinguishable from compliance in every artifact.

This ADR makes the control executable. It is deliberately narrow: it builds invocation surfaces and rewires the prose to name them. It does not redesign the matrix's *semantics*, with two exceptions forced by AF-2 and AF-3, both of which are about making the existing semantics actually reachable rather than changing what they say.

---

## 2. Decisions (BINDING on `technical-design`)

### AD-1 — Three layers, with the existing library untouched at the bottom. (BINDING.)

```
  L1  scripts/automation/lib/merge_authority.py    pure logic, signatures UNCHANGED
        ^ imported by
  L2  scripts/automation/merge_authority_cli.py    read-only primitives      (Q1 objective a)
      scripts/automation/overseer_decide.py        composed decision surface (Q1 objective b)
      scripts/automation/overseer_act.py           mutations                 (Q1 objective c)
        ^ invoked by
  L3  bootstrap/merge_authority.sh                 read-only primitives
      bootstrap/overseer_decide.sh                 composed decision
      bootstrap/overseer_merge.sh                  approve + merge      (irreversible; isolated)
      bootstrap/overseer_escalate.sh               request-reviewer / dismiss-review / label
      bootstrap/overseer_bounce.sh                 record_pr_bounce
      bootstrap/overseer_embargo.sh                route_embargo
```

**L1 stays pure. Do not add `argparse` or `__main__` to `merge_authority.py`.** The primitives take *already-fetched data* — `has_human_approval(reviews, ...)`, `detect_human_hold_directive(comments, ...)`, `decide_merge_authority(..., reviews=, requested_reviewers=)`. A CLI cannot sanely accept a list of GitHub review objects as an argument, and it must not: the entire point is that the agent stops marshalling data. So **L2 owns fetch-and-marshal**, L1 owns decide. This also preserves the 157 existing tests' mocking model unchanged (AD-13).

**L2 is Python because the logic is testable there** (the human's standing preference, cited in ADR-035: *"Python so it is testable"*), and because `argparse` gives a precise, self-documenting argv contract.

**L3 is bash in `bootstrap/` because that is where every agent-facing GitHub wrapper the overseer already calls lives** (`post_comment.sh`, `post_review_thread.sh`, `query_issues.sh`, `edit_issue.sh`, `create_issue.sh`), it is the pattern the human's ruling named explicitly, and `bootstrap/**` is the **first-listed protected surface** in `scripts/framework/protected_surfaces.txt` — so the merge-decision surface inherits CODEOWNERS human gating on its own edits for free. L3 does exactly three things: resolve the token (`get_app_token.sh --app <role>` / revoke), invoke L2, pass through stdout and the exit code. No logic in bash.

**Rejected alternative — a single flat CLI on the library.** It collapses the fetch boundary into the tested logic, breaks the existing mocking model, and produces subcommands with unfillable parameters. **Rejected alternative — L3-only, no L2.** Then the sequencing and marshalling live in bash, untestable, and the "agent re-derives control flow" failure just moves one layer down.

### AD-2 — One CLI contract, applied to every surface without exception. (BINDING.)

1. **Fixed argv shape.** Every invocation is `bash bootstrap/<script>.sh --app <worker|overseer|human> --pr <N>` (or `--issue <N>`) plus a closed set of flags. **No free text on the command line, ever** — variable text goes via `--body-file` / `--summary-file`, matching `post_comment.sh` and `create_issue.sh`. No positional arguments that carry content. This is the property that makes the call allowlistable; it is not stylistic.
2. **stdout is exactly one JSON object. Always.** Diagnostics, progress and warnings go to **stderr only**. Never suppress stderr at any call site (the #1523 lesson, already encoded in `check_pr_reviewed.sh`'s header).
3. **Exit codes, fail-closed:**
   - `0` — the question was answered, *whatever the answer* (the reporter convention `check_pr_reviewed.sh` and `audit_predicate.py` already use); for a mutation, `0` means the mutation **completed**.
   - `2` — usage error (unknown flag, missing required flag, non-numeric `--pr`).
   - `3` — **refused**: a mutation's fresh recompute did not authorize the requested action (AD-5). This is a normal, expected outcome, distinct from failure.
   - `1` — operational failure: API error, auth failure, malformed data, partial mutation.
   A mutation that did not complete **must never exit 0.**
4. **A schema version field** (`"schema_version": 1`) on every emitted record, so a consumer can detect a shape change rather than silently mis-read one.
5. **No `--force`, no `--skip-*`, no env-var override, on any surface.** Flags may only ever make a check *stricter*. There is no input — flag, env var, label, PR body, or comment — that widens what may merge. (The `audit_predicate.py` AD-6 discipline, applied here.)

### AD-3 — The low-level primitive surface: `bootstrap/merge_authority.sh`, one subcommand per named entry point. (BINDING — Q1 objective (a).)

Read-only. Each subcommand fetches what its L1 function needs, calls it, and serializes the result. `--repo <owner/repo>` defaults to the `origin` remote.

| Subcommand | L1 function | Fetches | Emits (abridged) |
|---|---|---|---|
| `gate` | `detect_server_side_gate` | branch protection | `{autonomous_capable, reason, checked_contexts}` |
| `register --step <N>` | `check_register_completeness` | local worktree | `{bounce_required, failures[], reason_category, summary}` |
| `bounce-count --cid <cid>` | `bounce_count` | audit trail | `{cid, count, cap, at_cap}` |
| `human-approval --pr <N>` | `has_human_approval` | reviews + head SHA | `{has_approval, approver, approved_sha, head_sha, stale_approvals[]}` |
| `hold-directive --pr <N>` | `detect_human_hold_directive` | comments + head commit date | `{hold_active, comment_url, created_at, matched_phrase}` |
| `protected-surface --pr <N>` | `touches_protected_surface` | changed files | `{touches, matched_paths[]}` |
| `security-surface --pr <N>` | `touches_security_surface` | changed files | `{touches, matched_paths[]}` |
| `codeowners --pr <N>` | `codeowners.check_pr_files` | changed files + CODEOWNERS | `{required, matched_paths[], reason}` |

Three notes that are part of the binding, not commentary:

- **`touches_protected_surface` and the CODEOWNERS check are in scope** even though the issue's list omits them. `overseer.md:495-526` (the #1325 pre-matrix gate) instructs the overseer to *"Call `touches_protected_surface(changed_files, repo_root)` … directly, on **every cycle**"* and `:470-489` (SPEC-303b) to *"Call `check_pr_files()` from `scripts/oversight/codeowners.py`"* — identical defect, same page, same fix. #1325's finding (a cycle that printed "Auto-merging" from narrative memory of a protected-surface PR) is this issue's defect with a different function name. Omitting them would leave the fix half-applied on the exact gates that already failed once.
- **`_touches_security_surface` is promoted to public `touches_security_surface`.** It is documented as a matrix input in `overseer.md:538-542`; a leading underscore on a documented input is a naming error, and the CLI needs it for evidence reporting. Behaviour unchanged.
- **`route_embargo` is NOT in this table.** It posts a comment and applies labels — it is a mutation and belongs in AD-5's family (`bootstrap/overseer_embargo.sh`). The issue's scope list grouped it with the reads; that grouping is wrong and is corrected here. Keeping a write behind a read-only surface is precisely the confusion this ADR's read/write split exists to prevent.

### AD-4 — The composed decision surface: `bootstrap/overseer_decide.sh --app overseer --pr <N>`. (BINDING — Q1 objective (b). This is what the overseer calls per PR.)

Backed by `overseer_decide.py`, whose public entry point is a **function**, `compute_decision(...) -> DecisionRecord`, with the `__main__`/CLI a thin serializer over it. That split is load-bearing for AD-5: the mutation wrappers call the *function* in-process, not the CLI as a subprocess, so there is no re-entry point at which a recompute could be stubbed, mocked, cached or skipped.

**The internal sequence is fixed, in code, in the order `overseer.md` steps 3b→5 already specify.** The agent sequences nothing:

0. Resolve configuration from `machine-accounts.env` (AD-9) — never library defaults.
1. Fetch the PR object once: `head.sha`, author, title, labels, `requested_reviewers`, `draft`, `mergeable_state`, `base.ref`.
2. Fetch once and share: changed files, reviews, issue comments, head-commit timestamp. **One fetch per datum per invocation** — `overseer.md:407` already insists on this (*"using the SAME `comments` list … do not re-fetch"*); in code it is structural rather than an instruction that can be forgotten.
3. CODEOWNERS gate (SPEC-303b).
4. Protected-surface pre-gate (#1325).
5. `detect_server_side_gate` (R9.1.1).
6. `check_register_completeness(step)` (step 4a).
7. Out-of-scope-commit flag scan (SPEC-328) — detection only in v1; see AD-14.
8. `bounce_count(cid)`.
9. `detect_human_hold_directive`.
10. `prior_overseer_decision` scan (the `**Decision: HUMAN_REQUIRED**` header, #761).
11. `decide_merge_authority(...)` with every input threaded — including `head_sha`, which is **never** allowed to default (AF-4).

**Output — a single JSON decision record:**

```json
{
  "schema_version": 1,
  "computed_at": "2026-09-11T00:00:00Z",
  "repo": "owner/repo", "pr": 1357, "head_sha": "...", "cid": "...", "step": "N",
  "config": { "overseer_ceiling": "HIGH", "human_reviewer": "...",
              "overseer_handle": "...", "worker_handle": "...",
              "tier_ceiling_check_name": "require-tier-ceiling",
              "config_source": "scripts/framework/machine-accounts.env" },
  "checks": [ { "name": "protected_surface", "result": "clear|flagged|error",
                "evidence": { }, "source": "merge_authority.touches_protected_surface" } ],
  "disposition": "AUTO_MERGE|PROPOSE_ONLY|HUMAN_REQUIRED",
  "reason": "<verbatim MergeAuthorityResult.reason>",
  "labels_to_add": [],
  "merge_permitted": false,
  "merge_authorization": null,
  "next_action": "MERGE|REQUEST_HUMAN_REVIEWER|ESCALATE_HUMAN|BOUNCE_WORKER|PROPOSE_ONLY_NOTICE|NO_ACTION",
  "idempotency": { "already_reviewed_this_head": false, "duplicate_comment_precheck": "post|skip" },
  "not_verified": [ "<checks that errored or were skipped, and why>" ]
}
```

Three fields carry specific weight:

- **`checks[]` is per-check evidence, as Q1 requires** — each entry names the L1 function that produced it. A decision record is auditable without re-running anything, and a divergence between the record and a later human's reading is locatable to one check.
- **`next_action` is a closed enum naming the wrapper to call next.** After this call the agent's remaining job is *"invoke the wrapper `next_action` names"* — not *"decide what to do."* This is Q1's general rule taken to its conclusion: the agent interprets nothing between the read and the act.
- **`not_verified[]` is mandatory and must never be empty-by-omission.** `overseer.md:563` already requires the executive summary to state what a run could not verify, and that *"silence must never be the encoding for 'complete.'"* Here it is a machine-produced list, not agent recollection. A check that errored appears here **and** sets `result: "error"`, and any errored check forces `next_action: ESCALATE_HUMAN` (fail-closed) — an unevaluable gate is never a passed gate.

The record also carries the #1524 already-reviewed and #1215 duplicate-comment precheck results so the agent does not re-derive those either.

### AD-5 — Mutations recompute fresh, in-process, every invocation, and refuse unless the fresh result authorizes the requested action. (BINDING — Q6, verbatim. This is R9.1.1 becoming real.)

Every mutation wrapper — `overseer_merge.sh`, `overseer_escalate.sh`, `overseer_bounce.sh`, `overseer_embargo.sh` — has the same mandatory, non-optional, non-skippable first step:

```
result = overseer_decide.compute_decision(repo, pr)     # fresh, in-process, every time
if result.next_action != <this wrapper's action>:
    emit {"refused": true, "requested": ..., "computed_next_action": ...,
          "reason": ..., "decision_record": {...}}
    exit 3                                               # nothing is written, nothing is called
```

Binding properties:

- **No pre-existing decision record is ever read, matched, or trusted.** Not by head SHA, not by timestamp, not at all. The human's reasoning is recorded and binds: *a record keyed on head-SHA alone doesn't catch a review being dismissed after the decision was computed with no new commit — same SHA, changed approval state, stale record would still "match."* Recomputing eliminates the staleness question rather than bounding it.
- **The recompute is an in-process function call, not a subprocess or a caller-supplied argument.** The wrapper cannot be handed a decision record to act on. There is no `--decision-file`. This is what makes the mechanism independent of the agent remembering to call the decision step first.
- **Refusal is a first-class, expected outcome** (exit 3, structured, with the full decision record attached), not an error. An agent that gets a refusal has everything it needs to report why, without narrating.
- **A refusal is auditable.** Each refusal writes its own audit event so "the overseer tried to merge and was refused" is durably visible — the absence-must-be-affirmed principle applied to this mechanism's own operation.

### AD-6 — The merge staleness bar is `mergeable_state == "clean"`. Branch currency with `main` is NOT required. (BINDING — the human's 2026-09-10 finalization.)

`overseer_merge.sh` asserts, on the **freshly fetched** PR object: `mergeable_state == "clean"` and `draft == false`. It does **not** compare the branch's merge-base against `main`, and must not acquire such a check later without a new human ruling. The two recorded reasons bind:

1. **#1216 established that branch currency does not catch the actual risk.** No required check executes tests against the *combination*, so "up to date with `main`" is a false sense of safety against cross-branch semantic interaction, not a gate against it.
2. **Throughput.** A strict currency requirement cascades: every merge invalidates every other queued PR, forcing serial rebase-and-recheck and defeating parallel PR queuing.

**Division of responsibility, restated so it is not re-opened:** per-PR merge decisions scope to *this PR's own content and current approval state*, recomputed fresh (AD-5). Cross-branch semantic interaction is **#1340's** job, at release time, against the accumulated diff.

**One implementation constraint I add:** GitHub's `mergeable_state` is eventually consistent and returns `"unknown"` while the mergeability background job runs. The wrapper **re-polls a bounded number of times and then refuses** (exit 3) — `"unknown"` is never treated as `"clean"`. Fail-closed, no exceptions.

### AD-7 — Approve-and-merge is ONE call, not two. (BINDING.)

`overseer.md:448` already requires both the approval review and the merge, and warns *"Both calls are required — approve without merging leaves the PR open."* A requirement phrased as *"remember to do the second thing"* is the same class of instruction this whole ADR is replacing. `overseer_merge.sh` performs, internally, as one unit: recompute → refuse unless authorized → `POST /pulls/{n}/reviews` (APPROVE) → `PUT /pulls/{n}/merge` (`squash`) → write the audit events → emit the result.

**Partial-failure handling is explicit and loud.** If the approval succeeds and the merge fails, the wrapper emits `{"approved": true, "merged": false, "error": "..."}`, applies `needs-human` (the fallback `overseer.md:448` already specifies), and exits **1** — never 0. A half-completed merge must never look like a completed cycle.

`overseer.md:452-458`'s batch-merge serialization (#6b) stays the caller's loop over single-PR invocations; because each invocation recomputes fresh (AD-5), the "re-check each PR's approval before each merge" requirement is satisfied structurally rather than by instruction.

### AD-8 — `_dep_ceiling_check_present` is implemented in this issue's scope; `_verify_overseer_review_accepted` must be resolved before the gate may be declared detected. (BINDING on both; **activation** is ESC-2.)

**On AF-2.** The DEP is fulfilled, the constant is provisioned, and the stub is stale. Implementation: read `required_status_checks` from the branch-protection object **already fetched by `detect_server_side_gate`** (no second API call) and return `True` iff `TIER_CEILING_CHECK_NAME` — resolved from `machine-accounts.env`, never hardcoded — appears in `contexts[]` or `checks[].context`. Any read failure, absent protection, or absent `required_status_checks` returns `False` with a reason naming what was missing (fail-closed, matching the function's existing contract).

**This is in scope for this issue's build, not deferred,** because the alternative is shipping a correctly-invoked control that is guaranteed to return the same answer for every PR forever — replacing narration with a constant. That is not a fix.

**On AF-3.** `_verify_overseer_review_accepted` is a permissive stub that becomes load-bearing the instant the above lands. It must be **either implemented** (read `required_pull_request_reviews.require_code_owner_reviews` and verify it, consistent with the SPEC-303b CODEOWNERS gate the decision surface already runs at AD-4 step 3) **or its claim removed** (delete the function and its call site, and amend `detect_server_side_gate`'s reason string so it no longer asserts a CODEOWNER property it does not check). What is **not** permitted is leaving an always-true stub inside a gate the system will now actually trust. `technical-design` chooses between implement and remove and justifies the choice; either satisfies this binding.

**The consequence that must be stated loudly, and is ESC-2.** Until the AF-2 fix lands *and* the live branch protection actually requires `require-tier-ceiling`, a correctly-invoked `overseer_decide.sh` returns `PROPOSE_ONLY` for every PR that would otherwise auto-merge, and `overseer_merge.sh` refuses **every** merge. **Landing the wrappers without the DEP fix halts autonomous merging entirely.** That is a deployment-topology and throughput consequence with a product-visible effect, so per the CORE product-boundary checkpoint it is routed to the human (ESC-2) rather than bound by me.

There is an elegance worth naming: because AF-2's implementation reads *live* branch protection, the human controls activation by configuring branch protection, not by editing code. The code is honest either way. No feature flag is needed, and none may be added (AD-2 rule 5).

### AD-9 — All configuration is resolved from `machine-accounts.env` at L2; library defaults are never relied upon. (BINDING — AF-4.)

`overseer_decide.compute_decision` resolves `OVERSEER_CEILING`, `HUMAN_REVIEWER`, `BOT_OVERSEER_USERNAME`, `BOT_WORKER_USERNAME`, `BOT_ACCOUNTS` and `TIER_CEILING_CHECK_NAME` from `scripts/framework/machine-accounts.env`, **fails loud** if the file or any required key is absent (never silently falls back to a Python default), and **echoes every resolved value plus its source path into the decision record's `config` block** — so every decision is self-describing and a mis-configuration is visible in the artifact rather than inferable from behaviour.

**Reuse the existing loader.** `require_tier_ceiling.py` already parses this file (per `tests/framework/test_require_tier_ceiling.py:244-249`) and `scripts/automation/lib/config_resolver.py` exists. `technical-design` picks one and reuses it. **Do not coin a third env parser** — that is the #1135 duplicate-authority class, and this repo has already paid for it once.

`head_sha` is a required, non-defaulting input to every human-approval lookup. It is never permitted to be `None` in any code path L2 reaches.

### AD-10 — Audit events are a forced side effect of the wrappers, not a step the agent is trusted to remember. (BINDING; `bounce_count`'s read side carries a named dependency on #1538 CR-1.)

Every mutation wrapper writes its own audit event via `audit_log.write_event`, in the halt-on-failure order `overseer.md:634-641` already specifies — post the comment → confirm posted → append the event → finalize; halt without finalizing if either the post or the append fails. `record_pr_bounce` (`:1092-1107`) **already implements exactly this**, correctly. It has simply never been called. **This is why #1356 ("bounces observed but no `pr-bounced` events reach the audit log") resolves substantially as a byproduct of this ADR** rather than needing its own mechanism — the event was never missing, the invocation was. This ADR does not take on #1356's remaining investigative scope.

Every wrapper (including the read-only ones, and including AD-5 refusals) records that it ran. A control that executes must leave evidence it executed, or the next investigation is right back where #1357 started.

**Named dependency on #1538 CR-1 — design against it, do not assume today's shape.** `bounce_count` currently streams the entire audit trail and filters in Python (VF-3). CR-1 requires the audit read side gain server-side filtering plus higher-level named-question CLIs. Binding: the `bounce-count` subcommand expresses its query **declaratively** — "count events where `event == "pr-bounced"` and `cid == X`" — behind a single internal call site, so that when CR-1's filtered-read primitive lands, `bounce_count` delegates to it by changing one function rather than being rewritten. Until then the current scan stands and is not a blocker. Do **not** redesign audit logging here; that is #1538's.

### AD-11 — Prose replacement: `overseer.md` and `overseer-cron-prompt.md` name wrappers; the contract needs three lines. Wrappers land FIRST. (BINDING.)

Per AF-1, the contract carries no R9.1.1 text — the work is concentrated in `overseer.md`. The replacement table `technical-design` must produce, at minimum:

| Location (`origin/main`) | Today | Becomes |
|---|---|---|
| `overseer-cron-prompt.md` Step 1 | *"run the full review chain (validators, size check, register completeness, merge-authority matrix)"* | a literal `bash bootstrap/overseer_decide.sh --app overseer --pr <n>` line, written in the **same shape** as the adjacent #1524 `check_pr_reviewed.sh` block, with the same never-suppress-stderr rule (AF-6), followed by "act on `next_action`" |
| `overseer.md:277` (step 4) | *"Re-detect server-side gate (`merge_authority.py:detect_server_side_gate`) — R9.1.1"* | folded into `overseer_decide.sh`; the R9.1.1 sentence **stays verbatim** and gains "…which `overseer_decide.sh` performs internally on every invocation, and which every mutation wrapper re-performs before acting" |
| `overseer.md:278-281` (step 4a) | *"call `record_pr_bounce(...)`"*, `bounce_count(cid) < 2` | `bash bootstrap/overseer_bounce.sh --app overseer --pr <n> --summary-file <path>`; the cap is evaluated inside `overseer_decide` and surfaces as `next_action: BOUNCE_WORKER` / `ESCALATE_HUMAN` |
| `overseer.md:336-435` (step 5) | ~100 lines instructing the agent to fetch reviews/comments/reviewers and thread ten parameters into `decide_merge_authority()` | **deleted and replaced** by a reference to `overseer_decide.sh`'s record. The parameter-threading prose is the largest single narration surface in the file; it describes work the agent must now not do. Retain the *rationale* paragraphs (#741 staleness, #761 idempotency, #902 hold, #1215 duplicate-comment) as **explanatory notes on the record's fields**, so the reasoning survives and the instruction disappears |
| `overseer.md:386-397` | a `python3` import snippet for `detect_human_hold_directive` | deleted — replaced by the `hold_directive` check in the record (this snippet is the most literal instance of the defect: an import statement given to an agent that cannot import) |
| `overseer.md:448-451` (step 6) | inline REST calls for approve / merge / request-reviewer / dismiss / label | the four mutation wrappers, by name |
| `overseer.md:495-526` (#1325 gate) | *"Call `touches_protected_surface(…) directly"* | folded into `overseer_decide.sh` step 4; the #1325 rationale paragraph **stays** (it explains why the check is unskippable) |
| `overseer.md:696-697` | *"Merge: no wrapper yet"*, *"Request reviewer: no wrapper yet"* | replaced with the wrapper names — these two lines are the standing admission this ADR closes |
| `overseer.md:666-674` (script table) | five wrappers listed | six new rows |
| `contract/OVERSIGHT-CONTRACT.md:429/435/454` | `record_pr_bounce` named as the `pr-bounced` producer | add the wrapper name alongside the function name; **no other contract change is required** |

**Ordering is binding and is the human's own instruction:** *"build the wrapper(s) first, then update the agent-file instructions to call them — not the reverse, or the instructions will again describe a capability that doesn't exist yet."* AF-6 supplies the counter-example that proves the ordering matters: the 2026-08-13 comment recorded that `overseer.md:722-726`'s prose about a *future* sandbox constraint changed behaviour immediately, in an environment where the constraint did not yet exist — *documentation is not inert.*

`.claude/agents/**`, `contract/**` and `bootstrap/**` are all protected surfaces, so the prose slice is human-gated at PR time regardless of anything here.

### AD-12 — `open_draft_pr` gets no wrapper. (BINDING — AF-7.)

No invocable surface is built for it. Building one would hand the overseer a tool for an action its charter forbids (`overseer.md:7`), and it has no caller. A separate issue tracks deleting it or relocating it to the worker's surface with justification. This is consistent with the binding 2026-09-10 scope list, which omits it; it is not a narrowing of the human's ruling.

### AD-13 — CLI tests prove wiring; the 157 existing library tests prove logic, stay untouched, and are not duplicated. (BINDING.)

The existing tests pass today against a module nothing invokes — they are a correct test of a correct library and a *vacuous* test of the system. The new tests make a **categorically different claim**. Required, at minimum:

1. **argv contract** — every documented flag parses; an unknown flag exits 2; a non-numeric `--pr` exits 2.
2. **Fetch→call marshalling** — a recorded API payload reaches the right L1 parameter. This is the class AF-4 names: a test that asserts `head_sha` actually arrives at `_find_human_approval` and is not silently `None`.
3. **Config resolution** — the ceiling comes from `machine-accounts.env` (`HIGH`), not the library default (`LOW`); a missing key fails loud.
4. **Record schema stability** — every documented field present; `disposition` and `next_action` only ever take closed-enum values; `not_verified[]` is populated when a check errors.
5. **Refusal tests — the ones that would have caught #1357.** For each mutation: a non-affirmative decision → exit 3, and **no GitHub write is attempted** (assert the mocked write call count is zero). Plus: no input path — flag, env var, or argument — reaches a mutation without a recompute.
6. **Fail-closed tests** — errored check → `ESCALATE_HUMAN`; `mergeable_state: "unknown"` → refuse; absent branch protection → gate not detected.
7. **The doc↔tooling reference check.** An executable test asserting that every wrapper named in `overseer.md` and `overseer-cron-prompt.md` **exists and is executable**, and — the converse — that neither file instructs the agent to "call `<function>(...)`" for any function in `merge_authority.py`. This is #1123's drift detector, scoped narrowly enough to build now, and it is the structural fix for the *class*: prose can never again name a surface that does not exist, nor re-grow a function-call instruction.

### AD-14 — Ship-set and portability. (BINDING — AF-5.)

The new L3 wrappers, their L2 modules, and the `scripts/automation/lib/` modules they import must be added to `scripts/framework/framework_consumer_files.txt` (the single source of truth for both the install copy-loop and `.hos-manifest`), **or** this ADR must declare the surface HOS-repo-only and `overseer.md` must say so. `technical-design` picks one and states it. Silently shipping a seventh wrapper that consumer installs never receive is not an option — that is AF-5's existing bug, reproduced deliberately.

`technical-design` must also verify the import path works post-install: L2 imports `scripts.automation.lib.*` as a package, which requires the package roots and `__init__.py` files to be present in a consumer install. This is a **TD-verification item**, not an assumption.

---

## 3. Escalations — held for the human (I do not bind these)

### ESC-1 — Does `merge_permitted` include an above-ceiling, human-approved merge path? (Product/policy. **Blocks AD-5's affirmative test for the CRITICAL path.**)

There is a **live contradiction** between the matrix and the prose that narration has been papering over, and making the control executable forces it into the open:

- `decide_merge_authority:607-612` returns **`HUMAN_REQUIRED`** whenever `risk_tier > overseer_ceiling` — **unconditionally**, before any human-approval check. A human approval does not change this result.
- `overseer.md:449` instructs, for **HUMAN_REQUIRED (CRITICAL tier)**: *"if ScottThurlow has approved, merge immediately"* — and `:438` (*"merge on next cycle after his approval satisfies branch protection"*) says the same, citing an explicit human authorization dated 2026-06-19 (#598/#599/#600).

Under AD-5 as written, `overseer_merge.sh` refuses any PR whose fresh `next_action` is not `MERGE` — so the CRITICAL-after-human-approval merge becomes **impossible**. Under narration, the agent simply did what the prose said. The two artifacts have disagreed since 2026-06-19 and nothing surfaced it, because the matrix was never run.

**Options:**
- **(a)** Add a second affirmative authorization, `HUMAN_APPROVED_ABOVE_CEILING`, computed *inside* the decision layer (never re-derived by the wrapper): when `tier > ceiling` and a verified human approval exists on the current head SHA, set `merge_permitted: true` with that authorization. This encodes the behaviour `overseer.md` already instructs and the human already authorized in 2026-06-19.
- **(b)** Bind `merge_permitted` to `disposition == AUTO_MERGE` only, and amend `overseer.md:438`/`:449` so above-ceiling PRs are merged by the **human**, not the overseer.

**Why this is yours and not mine.** Option (a) means an autonomous agent executes merges above its own trust ceiling — the OVERSEER_CEILING ratchet's entire purpose (`AGENT-IDENTITY.md §7`, #167). It may well be the right answer, since a verified human approval on the exact head SHA is a stronger authorization than the ceiling is a restriction. But it is a change to *who merges what*, and it will actually take effect for the first time — the behaviour has been narrated, not executed. Per the CORE product-boundary checkpoint, that is not mine to bind. **My recommendation is (a)**, on the grounds that it encodes an existing explicit human authorization rather than creating new authority, and that (b) would silently reduce throughput on exactly the PRs the human has already reviewed. I have not bound it.

### ESC-2 — Activating `_dep_ceiling_check_present` restores (or, if deferred, halts) autonomous merging. (Deployment topology + throughput. Product-boundary checkpoint.)

Two facts and one thing I could not verify:

- Landing this ADR's wrappers **without** AD-8's fix halts autonomous merging entirely — the correctly-invoked decision surface returns `PROPOSE_ONLY` for every otherwise-clean PR, and every merge is refused. This is *correct fail-safe behaviour*; it is also a material throughput change from today's observed state (#1341 merged autonomously on 2026-08-12).
- Landing it **with** the fix restores autonomous merging — but for the first time via the real matrix rather than an LLM's reading of it, and the two have already been observed to disagree (PR #1365, 2026-08-14).
- **I could not read live branch protection** (no wrapper exists for branch-protection reads; see §0 verification gaps), so whether `require-tier-ceiling` is currently a required check — and therefore whether AD-8's fix returns `True` or `False` in practice — is unknown to me.

**Decisions that are yours:** (i) confirm `require-tier-ceiling` is in the required-checks list on `main` (or accept that autonomous merging stays off until it is); (ii) confirm no bypass actor is configured for the overseer App; (iii) accept the interim window between the wrappers landing and the DEP fix landing, or require them in the same PR. AD-8 binds the *implementation*; activation is configuration you own.

### ESC-3 — Is a retrospective audit of previously-narrated dispositions required? (Human judgment; no correct technical answer.)

Every overseer disposition in the recoverable audit history was produced by narration. The one cycle where the matrix was genuinely run disagreed with narration's answer. The forward fix makes future dispositions real; it says nothing about past ones. **Is a retrospective review of prior autonomous merges required, or is the forward fix sufficient?** The mitigating context from the 2026-08-13 comment stands and should inform the call: the observed merges in the audit window were overwhelmingly human-authorized (27 `human-authorized-merge` events), and the CI gates (`require_human_approval.py`, `require_overseer_approval.py`, `require_tier_ceiling.py`) are real workflows that genuinely execute — so the *outermost* blocks were machine-enforced throughout. The exposure is the **routing** decision (what got escalated vs. auto-merged), not the final human/protected-surface gate. Neither dismiss nor overstate it; I decline to decide it.

---

## 4. Build order

Wrappers before prose (the human's instruction), reads before writes, and the behaviour-changing slice isolated so its effect is visible before it is depended upon.

| # | Slice | Contents | Gate to proceed |
|---|---|---|---|
| **1** | Primitives | `merge_authority_cli.py` + `bootstrap/merge_authority.sh`; promote `touches_security_surface`; AD-9 config resolution; AD-13 tests 1–4 | Every primitive invocable from a fixed argv line; 157 existing tests still green |
| **2** | Decision surface | `overseer_decide.py` (`compute_decision` + CLI) + `bootstrap/overseer_decide.sh`; full record incl. `checks[]`, `next_action`, `not_verified[]` | Record produced for a real PR and manually compared, field by field, against a hand-evaluation — the last time a human checks the matrix by reading it |
| **3** | Read-only observation window | Wire slice 2 into `overseer-cron-prompt.md` **for logging only** — the overseer calls it and records the record alongside its narrated disposition; no wrapper acts on it yet | Divergence between the computed record and the narrated disposition is measured, not assumed. **This is the empirical payoff of the whole issue** and must not be skipped for speed |
| **4** | Mutations | `overseer_act.py` + `overseer_merge.sh` / `overseer_escalate.sh` / `overseer_bounce.sh` / `overseer_embargo.sh`; AD-5 fresh recompute; AD-7 atomic approve+merge; AD-10 audit side effects; AD-13 tests 5–6 | **Blocked on ESC-1** (the affirmative test for the CRITICAL path is undefined until it is answered) |
| **5** | Gate stubs | AD-8: `_dep_ceiling_check_present` implemented; `_verify_overseer_review_accepted` implemented or removed; `test_merge_authority_detection.py`'s stub-encoding docstring and expectations updated | **Blocked on ESC-2.** Land as its own PR, never bundled — this is the slice that changes what merges |
| **6** | Prose + ship-set | AD-11 replacement table across `overseer.md`, `overseer-cron-prompt.md`, contract §6a; AD-13 test 7 (doc↔tooling reference check); AD-14 ship-set | Protected-surface PR — human-gated by CODEOWNERS regardless |

Slices 1–3 are independently valuable and unblocked: they make the matrix *observable* without changing a single disposition. If ESC-1/ESC-2 stall, slice 3 still converts #1357 from an assertion into a measurement.

---

## 5. Non-goals — named, with owners

- **Audit-logging redesign** — #1538. This ADR consumes the audit seam and declares one forward-looking dependency (AD-10); it designs none of it.
- **The broader sandboxed-role script inventory** — #1542, explicitly sequenced after this issue and excluding its scope. The one adjacent gap I hit — no wrapper for branch-protection reads (§0) — belongs to #1542, not here.
- **Cross-branch semantic interaction** — #1340, at release time (AD-6).
- **#1356's remaining investigative scope** — resolves substantially as a byproduct (AD-10); this ADR does not adopt the rest.
- **The matrix's semantics** — unchanged, except where AF-2/AF-3 make existing semantics reachable (AD-8) and where ESC-1 forces a contradiction into the open.
- **`pr_readiness.py`'s own invocation status** — the issue's residual check. Same defect class, separate surface, not designed here.
- **#1360's "invert the driver"** — v0.7.10. This design is an instance for it to generalize from.

---

## 6. Startup-gap analysis and affected sign-offs

**Should this have been settled in an initial architecture review?** Yes. `merge_authority.py` was built (B4, then B10) as a library with no invocation surface, and `overseer.md` was authored to instruct *"call `function(...)`"* against an agent whose only capability is issuing shell commands. The gap is in the **original B4/B10 design**, not in a revision of a prior ADR of mine — there is no superseded ADR here to orphan sign-offs against.

**Sign-offs that stand.** All 157 library unit tests and their sign-offs stand unchanged. The logic was correct and is not being modified (AD-1 keeps L1 signatures untouched). `test_merge_authority_detection.py`'s docstring and expectations encode the stub state and need updating in slice 5, but that is a scope change, not an invalidated approval.

**What is orphaned — and it is not a register entry.** Every overseer *disposition* recorded between the library's ship date and this fix was produced by narration, not by the matrix. These are not sign-offs in the §3 register sense, so no register entry is invalidated; but they are **unaudited outputs of a control that was believed to be executing.** That is exactly the "late correction must not leave prior approvals unaudited" condition, in a form the register schema does not cover. I record it here rather than let it pass silently, and I route the disposition of it to the human as **ESC-3** rather than deciding unilaterally that the forward fix suffices.

**One startup-gap issue should be opened** (or #1357 annotated) noting that the missing invocation surface was an original-design gap in B4/B10, so the lesson attaches to the design phase rather than only to the fix — feeding #1243's core-principles register with *"a control must be executed, not narrated"* (#1359).

---

## Human Review Required

Three items, all from §3, none of which I may bind:

1. **ESC-1 — the above-ceiling human-approved merge path.** Option (a) or (b)? Recommendation: **(a)**. Blocks build slice 4.
2. **ESC-2 — activation of the tier-ceiling gate detection.** Confirm `require-tier-ceiling` is a required check on `main` and no bypass actor exists for the overseer App; accept or reject the interim window in which autonomous merging is halted. Blocks build slice 5.
3. **ESC-3 — retrospective audit of previously-narrated dispositions.** Required, or is the forward fix sufficient?

Build slices **1–3 are cleared to proceed** without these answers and deliver the measurement that turns #1357's finding into evidence.
