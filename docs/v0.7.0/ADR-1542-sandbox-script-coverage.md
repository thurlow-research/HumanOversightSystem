# ADR-1542 — Script coverage for sandboxed Worker & Overseer: inherit one CLI contract, close the read namespace, and refuse to ship a capability list the system cannot check

**Status:** ACCEPTED FOR DESIGN — binds `technical-design`. **Three items are held for the human** (§3): ESC-1 (activating the worker lifecycle libraries, which have never executed — product boundary), ESC-2 (the autonomous roles' actual enforcement posture, which determines whether the FR-8 artifact is a control or documentation), ESC-3 (whether parallel v0.7.0 work may keep adding agent-instructed library calls before the detector lands). Everything else below is **BINDING**.
**Date:** 2026-09-12
**Author:** `architect`
**Verified against:** `origin/main` @ `511e2a2f` (2026-09-12). The requirements document was verified against `dfa9bf8e`; twelve commits have landed since, and four of them change this issue's inventory (§0).
**Source issue:** #1542 (open, `needs-human`, v0.7.0 — Quality).
**Inputs:** `docs/v0.7.0/REQUIREMENTS-1542-sandboxed-autonomous-roles.md` (merged PR #1596); #1542's full comment history — the **layered-CLI ruling** (2026-09-10), the **zero-friction acceptance bar** (2026-09-11), and the #1552/#1553 additions; `docs/v0.7.0/ADR-1357-merge-authority-execution.md` (merged `ecd35516`, 2026-09-11); `docs/SANDBOX-POLICY.md`; my own re-verification (§0).
**Consumers:** `technical-design` (next), then `needs-ai` build issues, v0.7.0 milestone.
**Blocks:** #1146 / #1053 (v0.7.4). This issue is their script-coverage prerequisite.
**Explicitly does NOT re-litigate:** the layered-CLI question (**ruled on #1542, 2026-09-10: build both levels** — so the requirements document's blocking **Q1** is already answered and I bind on it, §0/AV-2); the merge-authority surface's shape (ADR-1357, binding); #1538's mechanism (human ruled `pm-agent` skipped); the acceptance bar (ruled: **zero prompts**, not "approvable prompts").

---

## 0. Verification — what has changed since the requirements document, and what it changes

The requirements document is two days old and its §0 was rigorous; I did not re-derive the findings it already established from first principles, but I re-checked every one that this ADR binds on, plus everything the last twelve commits could have moved. Findings are `AV-#`. Six **correct or extend** the requirements document; three are **new and change the design**.

**AV-1 — CONFIRMS most of the requirements document's §0.** VF-4 (audit CLI takes the event on **stdin**, `read` is an unfiltered dump, the `.sh` facade is sourced-only — `audit_log.py:195-248`), VF-5 (`overseer-cron-prompt.md:38`'s `(source …audit_log.sh) run audit_read_stream | grep -F … | grep -F "\"pr\":<n>"`), VF-6 (the `for pr in $(gh api …)` loop at `:30`), VF-7 (`--jq "$(cat …/next_candidates.jq)"` at `worker-cron-prompt.md:101`), VF-9 (`check_pr_reviewed.sh <pr#> <head_sha> [root]` — positional, caller-supplied head SHA), VF-10 (`merge_authority.py` still has zero `__main__`), VF-11's core claim (no single-PR getter, no reviews/files/events/labels/commit getters), VF-12 (`SUPPORTED_ROLES = ("human",)`, `EXIT_UNSUPPORTED_ROLE = 3`), and VF-15's counts (15 raw `gh api` sites: `overseer.md` 4, `worker.md` 4, `overseer-cron-prompt.md` 4, `worker-cron-prompt.md` 3; 6 "no wrapper" annotations) **all hold**. Only the line numbers moved: the annotations are now `overseer.md:457, :671, :705, :708, :709` and `worker.md:327`. `pr_readiness.py` still requires all five caller-supplied arguments (`:685-689`).

**AV-2 — CORRECTS the requirements document's blocking status: Q1 is already ruled, and Q6 is superseded.** The requirements document classifies **Q1** (one decision surface vs. nine wrappers) as STRUCTURAL/BLOCKING and forbids me from binding it. It was in fact ruled by the human on **#1542 itself**, 2026-09-10T20:53Z — *"Unless the agent genuinely needs to interpret or make a decision on an interim step, provide a single call that performs the entire task,"* with both objectives named and *"(#1357, now resolved: build both)"* stated explicitly. ADR-1357 then bound it (AD-1's three layers). **Q1 is answered; I proceed on it and it is not escalated.** Likewise **Q6** ("should approve/merge refuse without a decision record from #1357's surface?") is **moot and its premise is now prohibited**: ADR-1357 AD-5 binds that mutations recompute *in-process, every invocation*, and that *"the wrapper cannot be handed a decision record to act on. There is no `--decision-file`."* A #1542 script that accepted a decision record would be a regression against a binding ADR. See AD-5 below.

**AV-3 — ADR-1357 merged and it already owns more of this inventory than the requirements document's boundary table allocates to it.** ADR-1357 AD-3/AD-5/AD-11 build `bootstrap/overseer_merge.sh` (approve **and** merge as one unit — AD-7), `bootstrap/overseer_escalate.sh` (**request-reviewer / dismiss-review / label**), `bootstrap/overseer_bounce.sh`, and `bootstrap/overseer_embargo.sh`. Its AD-11 replacement table states the mapping verbatim: *"`overseer.md:448-451` (step 6) | inline REST calls for approve / merge / request-reviewer / dismiss / label | the four mutation wrappers, by name."* **Consequence: FR-2.1–FR-2.4 (W1–W4) are entirely #1357's deliverable.** #1542's PR-write inventory is **zero net-new wrappers** (AD-5). The requirements document's §3.2 boundary table, which assigns "PR-write wrappers (W1–W4)" to #1542, is superseded on this row.

**AV-4 — CORRECTS VF-11's function inventory: `github.py` gained a PR-namespace read two days ago.** `list_check_runs_for_ref` now exists (`github.py:209`), added by `fa4132cb` (#1580, 2026-09-11). The module is now eight public functions. The gap VF-11 names is otherwise unchanged: no single-PR detail getter, no reviews lister, no changed-files lister, no issue-events lister, no labels lister, no commit getter.

**AV-5 — NEW, HIGH: the defect is being re-grown faster than it is being fixed, and there is a dated instance one day after ADR-1357 merged.** `fa4132cb` (#1580) added **97 lines to `merge_authority.py`** — a new public `check_required_content_checks()` — **29 lines to `github.py`**, and **12 lines of `overseer.md` prose** instructing, verbatim: *"Call `check_required_content_checks(owner, repo, head_sha, default_branch=<default_branch>)` on **every cycle**"*, with two more insertions making the CODEOWNERS and protected-surface gates conditional on it having "cleared this cycle." That is a brand-new, agent-instructed Python function call with **no invocable surface**, landed into the exact file ADR-1357 exists to de-narrate, one day after that ADR merged. Two consequences bind: (i) **Q12/FR-9.5 is not hypothetical** — it is the current default behaviour of parallel v0.7.0 work (AD-11, AD-19, ESC-3); (ii) **ADR-1357's AD-4 internal sequence is already incomplete** — step 4c is missing from its eleven-step list, and `technical-design` for #1357 must fold it in or the decision surface will silently omit a gate that `overseer.md` now requires (§3 ESC-3 note).

**AV-6 — NEW, HIGH: the worker lifecycle libraries have no runtime caller anywhere, and `worker.md` narrates them as function calls.** `git grep` over `origin/main` for importers of `claim`, `breakers`, `budget`, `triage`, `correlation`, `envelope`, `ledger` returns **only** tests, each other, `observability.py`/`probe.py`, and prose (specs, `SCRIPTS-INDEX.md`, `docs/LABELS.md`). `bin/hos-cron` imports exactly one automation module — `cycle_log` (`:364`) — and nothing else. Meanwhile `worker.md:363-385` instructs the agent: *"1. **Idempotency precheck** (`correlation.py:already_exists`) … 2. **Failure cap check** (`breakers.py:is_poisoned`) … 3. **Claim** (`claim.py:claim`) … 6. **Triage** (`triage.py:triage`) … 7. **Budget gate** (`budget.py:BudgetGate`) … 10. **Terminal release** — post claim-release envelope."* **This is the worker-side twin of #1357, and it is worse in one respect: these controls have never executed even under `bypassPermissions`, because no invocation form for them exists at all.** FR-3 is therefore not a friction fix. Building its CLIs *activates seven controls for the first time* — an autonomous-behaviour change (a worker that now genuinely budget-gates, poison-breaks and claims). That is a product-boundary item: **ESC-1**. Note also that `ledger._run_dir(customer)` and `probe`/`multi_customer` are customer-scoped — this subsystem was built for the #254 unattended-worker design and never adopted into HOS's own cron, which is why no caller exists.

**AV-7 — NEW, HIGH: the enforcement premise this whole issue rests on is not verified, and the tracked template says something inconvenient about it.** `contract/sandbox-policy.template.json` sets `"autoAllowBashIfSandboxed": true`, and `docs/SANDBOX-POLICY.md` §3 explains it as: *"Inside the sandbox, bash commands are not individually prompted … It is also why the `permissions.allow` list below is about **intent and auditability** more than about hard enforcement."* Taken literally, an autonomous policy carrying that key would make the FR-8 allowlist advisory and the silent-skip hazard mostly theoretical. Taken literally it is also **contradicted by measurement in this very session**: this Human clone runs that policy, and two Bash calls were **denied outright** ("running in don't ask mode") — one containing `$(…)` inside a `for` loop, one a `;`-chained `echo` + `git grep` — while several *other* `;`-chained and pipe-containing calls in the same session ran fine. So denial is real under `autoAllowBashIfSandboxed: true`, and it is **not a clean syntactic function of the command text**. Separately, `disableBypassPermissionsMode: "disable"` in the same template **blocks `bin/hos-cron:1764`'s `--permission-mode bypassPermissions` launch outright** — `SANDBOX-POLICY.md:96-99` already names this as the core unreconciled conflict of #1146. **Conclusion, binding as AD-13:** the enforcement surface is uncharacterized; design for the *strict* posture (deny-by-default, no prompts, silent skip on any unmatched call), because coverage is *necessary* under the strict posture and merely *beneficial* under the permissive one, and the reverse bet is unrecoverable. The posture itself is **ESC-2**.

**AV-8 — CORRECTS the requirements document's §3.4 disposition for #1216: it is CLOSED.** `#1216` is `state=closed`. FR-6.9 ("CI-invocable from day one") is therefore a constraint against *landed* CI, not a forward-looking one, and #1571 has since split `oversight-gates.yml` and `oversight-validators.yml` into per-job workflows with several promoted to **required** status checks (`077ecb46`, `622b637e`, `3a394b86`). That is the concrete substrate AD-11's detector and AD-19's enforcement attach to.

**AV-9 — CORRECTS VF-9's minor drift note, and finds the convention model.** `audit_predicate.py` **does** exist — at `scripts/framework/audit_predicate.py`, not `scripts/oversight/`. It is not doc drift about a nonexistent file; it is a path error about a real one. More usefully, it is the best existing model for this issue's CLI contract: a pure classifier, a documented `classify` subcommand, an explicit fail-closed rule, and the stated invariant *"There is no env var, label, branch, or PR-body input that widens qualification — narrowing only"* — which ADR-1357 AD-2 rule 5 already generalized. `technical-design` should read it before authoring anything.

**AV-10 — The git-write surface is under-counted, and one §3-table entry genuinely passes the stricter test.** Under a strict policy that does not allow `Bash(git *)`, the worker's ordinary loop loses `git add`, `git commit`, `git stash`, `git cherry-pick`, `git revert` — of which only commit (FR-4.1), cherry-pick/revert (FR-4.10/4.11) are inventoried; `git add` and `git stash` (`worker.md:373`'s *"stash or abort before dispatch"*) are not. Both cron prompts also contain `cd "$REPO_ROOT"` and `[ "$HOS_BOT_LOGIN" = "…" ] || exit 1` — `$VAR` expansion, four sites, only the latter inventoried (G10). Conversely, **`submit_pr.sh --update-pr <N>` genuinely covers push-to-an-existing-PR** with a caller-declared mode and a server-side authorship check — it passes FR-9.1's stricter test as written, and is the model for what "covered" should mean.

**AV-11 — No trailer-enforcing commit tooling exists.** `git grep "Prompt-Artifact"` across `scripts/`, `bootstrap/`, `bin/` hits only prompt-capture and validator code; nothing enforces the trailer set at commit time. FR-4.1 is real. The adjacent tool is `scripts/dev/commit_onto_base.sh` (plumbing-based, `--message-file`, no working-tree writes) — whose own header already argues this issue's thesis — and **#1552 records that it still prompts on a fully static invocation**, which under the zero-friction bar is a failure, not a nuisance.

**AV-12 — Ship-set and protected-surface facts, re-confirmed.** `scripts/framework/framework_consumer_files.txt` ships `bootstrap/create_branch.sh` and `bootstrap/lib/*` and nothing else from the agent-facing wrapper set — ADR-1357's AF-5 holds unchanged. `scripts/framework/protected_surfaces.txt` lists `contract/**`, `bootstrap/**`, `scripts/framework/**`, `.claude/agents/**` and `.github/workflows/**`. `gen_sandbox_config.py` reads exactly one template path (`TEMPLATE_RELPATH = "contract/sandbox-policy.template.json"`, `:122`) and its purity invariant is `render(template_text, values)` — **no path parameter, no merge mode**. The template already carries a `__ROLE__` placeholder (`__CONFIG_DIR__/__ROLE__.pem`).

### Verification gaps I could not close

1. **Live branch protection** — same gap ADR-1357 hit, for the same reason (no wrapper for branch-protection reads, and the only unwrapped path is the construct this issue exists to remove). Unchanged and still #1542's to fix (FR-1 family).
2. **Actual matcher behaviour** for `Bash(bash bootstrap/x.sh *)`-shaped rules, and for the interaction of `autoAllowBashIfSandboxed` with the auto-mode classifier. `SANDBOX-POLICY.md` §4 item 7 already records the matcher as UNVERIFIED. AV-7's in-session evidence says denial happens but not on a clean syntactic rule. **Nothing in this ADR may be read as a measurement of that** — AD-17 makes characterizing it a gated prerequisite.
3. **A per-call-site census** of `worker.md`/`overseer.md` — spot-checked, not exhaustive. FR-9.1's re-audit stands as `technical-design`'s deliverable, and AV-10 shows it will grow the inventory.

---

## 1. Context

Two facts set the frame. First, the acceptance bar is **zero prompts** (#1542, 2026-09-11): a command a human would happily approve is still a failure, because headless `claude --print` has no prompt UI and a denied call becomes a **silently skipped step** in a cycle that still exits 0. Second, the layered-CLI ruling (#1542, 2026-09-10): *primitives for unknown future composition, one call for known fully-specified sequences* — because "the agent composes the known sequence" is the same *agent re-derives the control flow* failure as narration, one level up.

ADR-1357 already applied both to the merge-authority surface and produced a three-layer architecture and a CLI contract. **This ADR's single most important decision is that #1542 adopts that contract wholesale rather than authoring a second one.** The rest is inventory: which surfaces remain, who owns them, and in what order they land.

---

## 2. Decisions (BINDING on `technical-design`)

### AD-1 — Inherit ADR-1357's layering and CLI contract verbatim. #1542 authors no second convention. (BINDING.)

Every surface this issue produces conforms to ADR-1357 **AD-1** (L1 pure library / L2 Python fetch-and-marshal + `argparse` / L3 bash in `bootstrap/` that resolves a token, invokes L2, passes through stdout and the exit code — no logic in bash) and **AD-2** in full: fixed argv shape with no free text on the command line (variable text via `--body-file`/`--summary-file`); **stdout is exactly one JSON object, always**; diagnostics to stderr, never suppressed; exit codes `0` answered / `2` usage / `3` refused / `1` operational failure; `"schema_version"` on every record; and **no `--force`, no `--skip-*`, no env-var override, on any surface — flags may only ever make a check stricter**.

Two coherence rules follow and are binding: a #1542 script **may not** introduce a second token-handling path (it calls `get_app_token.sh`/`revoke_app_token.sh` like every existing wrapper), and it **may not** coin a second env/config parser (ADR-1357 AD-9: reuse `config_resolver.py` or `require_tier_ceiling.py`'s loader — the #1135 duplicate-authority class).

**Rejected alternative — a lighter contract for "just reads."** A read wrapper whose output shape or exit convention differs from the decision surface's forces the agent to remember which convention applies to which script. That is a per-call judgement, which is what the layered-CLI ruling removes.

### AD-2 — All PR-namespace fetching lands as functions in `scripts/automation/lib/github.py`. One HTTP authority. (BINDING — resolves **Q3**, option (a).)

`github.py` already owns retry, backoff and rate-limit handling (#1213). The eight PR-read answers (FR-1.1–FR-1.8) become functions **there** and nowhere else. No L2 module issues its own `gh`/`curl` call; no wrapper re-implements pagination.

**Ownership split, resolving Q3 as the requirements document recommended:** #1357's L2 adds the functions its decision surface needs (single-PR detail, reviews, changed files, comments, head-commit timestamp — it needs all of them per ADR-1357 AD-4 step 2); **#1542 extends with the residual — issue events (FR-1.6), repo labels (FR-1.7), merged-PRs-with-`merged_by`-resolved (FR-1.5), and branch protection reads as an agent-reachable operation** — and adds the CLI over the whole set. This keeps #1357 unblocked and avoids a three-way dependency. **Binding constraint on #1357's slice:** functions added there must be authored as general-purpose `github.py` functions, not as private helpers inside `overseer_decide.py`, or #1542 inherits a fork.

### AD-3 — The read CLI is a new sibling, `bootstrap/query_prs.sh`, with **named operations only**. (BINDING — resolves **Q4** and **Q5**.)

**Q5 — a sibling, not an extension of `query_issues.sh`.** `query_issues.sh` is explicitly REST-issues-endpoint-shaped (its header states the REST-only rule and that every listing mode filters `.pull_request == null`); it already carries six mutually-exclusive modes. Adding eight PR-endpoint modes to it produces a script whose two halves share nothing but a token mint, and one allowlist entry covering both namespaces. Two scripts, one namespace each, is the legible capability list FR-8 demands.

**One exception, and it is deliberate:** `FR-1.9`'s in-wrapper matching for **comments** goes to `query_issues.sh --comments` as `--contains <literal>` / `--author <login>`, because comments *are* the issues endpoint and `query_issues.sh --comments <N>` is already the established, documented call for PR comments. Splitting comment reads across two scripts by subject type would be worse than the seam it avoids.

**Q4 — named operations only. No generic GET wrapper, ever.** A `--path <any>` / `--endpoint <any>` wrapper is an allowlist entry for *arbitrary authenticated GitHub API access*; it would forfeit the entire control while appearing to satisfy it, and it would let the long tail be absorbed silently instead of being surfaced as a reviewed addition. The long-tail cost is accepted and is the point: adding a named operation is a `bootstrap/**` PR, which is CODEOWNERS-gated. **Binding corollary:** no #1542 script may accept a caller-supplied URL, endpoint path, jq expression, or GraphQL query as an argument.

### AD-4 — Every read answers a *question*, not an endpoint, and derives what the repo already knows. (BINDING — FR-6.2, FR-1.10.)

Subcommands are named for the question (`--pr <N> --head-sha`, `--reviews`, `--files`, `--events`, `--merged-since <hours>`), emit one JSON object, and **derive every value the repo can derive**. Concretely and non-negotiably: `--repo` defaults to the `origin` remote; head SHA is *never* a required caller argument for any operation that can look it up; `check_pr_reviewed.sh` gains a `--pr <N>` form that derives the head SHA internally (VF-9) with the positional form retained for CI; `pr_readiness.py` gains a form that derives `--base-sha`/`--head-sha`/`--cid` from the branch and branch-ownership record; release tier derives the last tag itself (FR-4.4).

**Self-derivation is a property of the script, not an option on it.** A flag that merely *permits* derivation leaves the substituting call site legal and therefore alive in the prose. Where a value must remain overridable for CI, the override narrows (an explicit SHA) and never widens.

### AD-5 — #1542 delivers **no** PR-write wrappers, and **no** #1542 script accepts a decision record as input. (BINDING — supersedes FR-2 as scoped; **Q6** is moot.)

Per AV-3, FR-2.1–FR-2.4 are delivered by ADR-1357's `overseer_merge.sh` and `overseer_escalate.sh`. #1542's deliverable on this family is exactly two things: (i) FR-9.1's audit that they exist and are invocable with literal arguments; (ii) the FR-7 prose sweep of `overseer.md:457/:708/:709`, which must be coordinated with — not duplicated by — ADR-1357 AD-11's table.

**Q6 is answered by ADR-1357 AD-5 and in the opposite direction to the requirements document's recommendation.** Mutations recompute in-process every invocation and **cannot be handed a decision record**; there is no `--decision-file`. A #1542 wrapper introducing one would re-open the staleness question that AD-5 eliminated. Binding: **no script produced under this issue may accept a prior decision, verdict, or gate result as an input that permits an action.** Inputs may only narrow.

### AD-6 — The worker lifecycle (FR-3) is the worker-side #1357, and its *invocation surface* and its *activation* are separated. (BINDING on shape; activation is **ESC-1**.)

Per AV-6 these seven controls have never run. The shape, when built, mirrors ADR-1357 exactly — and the layered-CLI test gives a clean answer, because `worker.md:363-385` steps 1→3 and 6→7 are a **fully specified admission sequence with no interim agent judgement**:

- **L2** `scripts/automation/worker_admit.py`, public entry point `compute_admission(...) -> AdmissionRecord`: correlation precheck → breaker check → triage → budget estimate, emitting one record with `checks[]`, `not_verified[]` and a closed `next_action` enum (`CLAIM | EXIT_ALREADY_DONE | EXIT_POISONED | ROUTE_EMBARGO | ROUTE_HUMAN | BUDGET_GATED`).
- **L3** `bootstrap/worker_claim.sh --app worker --issue <N>` — the **mutation**, which calls `compute_admission` **in-process** (never as a subprocess, never from a file) and refuses with exit 3 unless `next_action == CLAIM`, then posts the claim envelope and applies `hos-claimed`. One call, because between "am I allowed to work on this" and "claim it" the agent decides nothing.
- **L3** `bootstrap/worker_release.sh --app worker --issue <N>` — terminal release envelope + label removal, same discipline.
- **L3** `bootstrap/worker_lifecycle.sh` — read-only primitives (`admit`, `breaker-status`, `budget-estimate`, `triage`, `correlation`), satisfying the ruling's objective (a) for compositions not yet known. Read-only; `record_task_failure` and ledger appends are mutations and get their own narrow wrappers.

**Binding either way, whichever way ESC-1 rules:** if the human rules *not* to activate, this issue ships **no** worker lifecycle CLI and instead **deletes the narration from `worker.md:363-385`**. A control the system does not intend to run must not be written as an instruction — AF-6/#1357's finding that *documentation is not inert* cuts both ways, and leaving seven fictitious function calls in the worker's charter is the exact condition #1357 exists to end.

### AD-7 — Compound git / release / audit operations: dispositions, each decided by the layered test. (BINDING.)

The test applied to each: *does the agent make a real decision between these steps?* If no → one call. If yes → primitives.

| FR | Capability | Ruling |
|---|---|---|
| 4.1 (G1) | Commit with enforced trailers | **One call.** `bootstrap/commit_work.sh --message-file <p> [--file <p>…]`, refusing on a missing trailer. **Binding:** the trailer validator is a *single shared module*, and `scripts/dev/commit_onto_base.sh` delegates to it — two trailer parsers is the #1135 class. #1552 (it still prompts) must be resolved as part of this item, not tracked separately; under the zero-friction bar an unexplained prompt on a static invocation is an unclosed defect. |
| 4.2 (G2) | §3b validator-artifact ancestry verdict | **One call.** Five chained git reads with substitutions, no interim judgement, one verdict. |
| 4.3 (G3) | PR readiness, self-derived | **Retrofit, not a new script** — AD-4 applied to `pr_readiness.py`. |
| 4.4 (G4) | Release tier, self-derived | **One call**, tier + required-suite list in one record. |
| 4.5 (G5) | NG3b R1 + R5 authorization verdict | **One call, and it is the highest-value item in this table.** The most intricate prose-only protocol in the system, re-evaluated by hand every cycle. Emits one verdict plus per-condition evidence in `checks[]` shape. **Binding:** R1 and R5 are two named subcommands plus a composed `status` — the agent may need R1 alone during triage, but must never assemble R5 from parts. |
| 4.6 (G6) | R3/R4 release results comment body | **One call producing a file**, consumed by `post_comment.sh --body-file`. Composition in code; the agent supplies inputs, never prose assembled from redirected substitution output. |
| 4.7 (G7) | Merged-PR sweep with `merged_by` resolved | **One call** (`query_prs.sh --merged-since <hours>`), replacing `overseer-cron-prompt.md:30`'s loop. Library half is AD-2's FR-1.5. |
| 4.8 (G10) | Identity assertion | **One call**, `bootstrap/assert_identity.sh --app <role>`, exit non-zero on mismatch. Replaces all four `$VAR`-expanding guard lines (AV-10). **Binding:** this does not replace the in-wrapper identity guard every mutation script already performs (ADR-1357 AD-2 / FR-6.3); it is the cron prompts' own opening assertion. Guards inside wrappers are never removed in favour of it. |
| 4.9 (G11) | Next-candidate selection | **One call** wrapping the canonical `next_candidates.jq`, since `hos-cron` already precomputes the list and this is the *fallback* path. |
| 4.10 (G12) | Dirty-PR branch rebuild | **One call, and it is not merely an allowlisting fix** — it closes the force-push path that bypasses `submit_pr.sh`'s merge-from-base guard (#1162's residual). Design it as `submit_pr.sh`'s sibling, sharing its authorship precheck; it must never force-push without the same server-side ownership verification. Own slice, own review. |
| 4.11 (G13) | Out-of-scope-commit handling (SPEC-328 Option A) | **One call.** Revert-on-branch → follow-up branch from target → cherry-pick is fully specified. |
| 4.12 (VF-8) | Release-gate validation against **committed** state | **New adapter, outside the pure module.** `release_artifact_logic.py`'s stated PURITY contract (no subprocess/network/git) must not be broken; the `git show origin/main:…` reads live in a thin L2 adapter that feeds it, with a self-derived version. |
| 4.13 (VF-9) | PR-review idempotency precheck | **Retrofit** (AD-4). |
| — | `git add` / `git stash` / dirty-tree handling (AV-10) | **New inventory item.** `technical-design` decides whether these fold into `commit_work.sh` (`--file` already implies staging) or need a `worker_worktree.sh`. Do not let it land as "the agent runs raw git." |
| 4.5 / FR-5 | Audit read/write | **Not #1542's.** Delegated to #1538 (AD-20). |

### AD-8 — Reads are reads; nothing in this issue's read surface may mutate. (BINDING.)

ADR-1357 AD-3's correction — `route_embargo` was mis-grouped as a read and is a mutation — is a rule, not an incident. Every #1542 surface is classified read-only or mutating **in its filename and its header**, a read-only script performs no POST/PATCH/PUT/DELETE and writes nothing outside `/tmp`, and no mutation hides behind a read-shaped name. The audit event a wrapper writes about *itself* (AD-20/ADR-1357 AD-10) is the sole exception and must be stated in each script's header.

### AD-9 — The FR-8 artifact is a **per-role tracked template**, deny-by-default, not derived from the human policy. (BINDING — resolves **Q9** mechanically.)

`contract/sandbox-policy.worker.template.json` and `contract/sandbox-policy.overseer.template.json`, siblings of the existing human template; `gen_sandbox_config.py` selects the template **by role** and `SUPPORTED_ROLES` grows to all three. The generator's purity invariant is preserved exactly: `render(template_text, values)` still takes no path parameter, and role selection happens in the caller that loads the text. **There is no merge mode and no inheritance from the human template** — a role-conditional single template would let the autonomous policy acquire the human policy's breadth by accident, and the human policy's breadth is the thing being removed: it allows `Bash(git *)`, `Bash(gh *)`, `Bash(curl *)`, `Bash(python3 *)` and `Bash(bash bootstrap/*)`, which is approximately "everything" and is correct *only* because a human is present.

**Q9 answers itself:** `contract/**` is the second entry in `protected_surfaces.txt`, so the artifact is CODEOWNERS-human-gated on every change with no new mechanism. That is the reason to put it there rather than in a generated sidecar.

**Binding content rule:** the autonomous allow list contains the wrapper scripts, the test/validator/gate runners, and an enumerated read-only git set — and the rule set must **state, in the file, the position distinction**: `git log`, `git status --short`, `git diff --stat`, `git rev-parse`, `git fetch origin` are permitted **as standalone reads whose output the model consumes**, never as substitutions inside another command. That is the one place the same text is safe in one position and fatal in another, and it must be written down rather than assumed.

### AD-10 — Enumerate wrappers by literal path, **and** ship the coverage check that makes enumeration safe. (BINDING.)

No `Bash(bash bootstrap/*)`-style prefix rule for the autonomous roles: FR-8 asks for a capability list, and a prefix grants every future file in a directory. But enumeration introduces its own silent-skip: a wrapper lands, the prose names it, the policy was not updated, and the cycle skips the step exactly as before. **So enumeration is only permitted together with a mechanical three-way check** — for each role: every wrapper named in that role's agent file and cron prompt **exists and is executable**, **and** appears in that role's policy allow list; and every allow entry naming a repo path **resolves to a file that exists**. Fail-closed, in CI, required. This is ADR-1357 AD-13 test 7 extended by one leg; build it as one check, not two.

### AD-11 — The detector (FR-9.2) is built **first**, before most wrappers. (BINDING — AD-19, ESC-3.)

The requirements document sequences the detector as an acceptance criterion. AV-5 makes that wrong: in the two days between the requirements document and this ADR, parallel work added a new agent-instructed, uninvocable library call plus its prose. A detector that lands last measures a surface that has been growing the whole time; a detector that lands first **stops the bleeding on day one** and gives every subsequent slice a green-to-red-to-green signal. It scans the four behaviour-driving documents for substitution, heredocs, `$VAR`-in-argument, `source`, `for`/`while`, pipes into `grep`, `&&`-chaining, and bare `gh api`.

**Extend its remit by one rule, which is the #1580 lesson:** it also fails on prose instructing the agent to **call a Python function** (`` `module.py:function` ``, `call `function(...)``, `python3 -c`, a bare `import` snippet) for any module under `scripts/automation/lib/` or `scripts/oversight/` that has no invocable surface. That single rule is what would have caught #1580's `overseer.md` edit in review, and it generalizes #1357 from a fix into a gate.

**Baseline debt is declared, not hidden.** The four documents will not be clean on day one. The detector lands with an explicit, enumerated, shrinking allowlist of known-failing sites (the #1571 "debt baseline" pattern already used in this repo), and every slice below removes entries from it. **No entry may be added to that baseline after the detector lands** — that is the gate.

### AD-12 — Wrapper, prose, allowlist entry and test land in one PR. (BINDING — FR-6.8 made mechanical.)

ADR-1357 AD-11's ordering (wrappers before prose) governs *across* issues; *within* a slice the four artifacts are one change, enforced by AD-10's coverage check and AD-11's detector rather than by reviewer attention. A wrapper landing without its prose replacement leaves the agent emitting the raw form; prose landing without the wrapper names a capability that does not exist. Both failures are already on the record in this repo.

### AD-13 — Design for the strict enforcement posture. Never rely on `autoAllowBashIfSandboxed`. (BINDING — AV-7.)

Every design decision assumes: deny-by-default, no prompt, unmatched call silently skipped. No script, prose instruction, or policy entry may be justified by "the sandbox would auto-allow it anyway." **And the FR-8 artifact must state its own enforcement status honestly** — if the eventual policy keeps `autoAllowBashIfSandboxed: true`, the artifact says in its header that the allow list is an *auditability and intent* record whose hard containment comes from the filesystem/network boundaries, rather than implying an enforcement it does not have. Claiming a control that does not fire is the failure class this entire issue family exists to end; it would be absurd to commit it in the artifact that closes it.

### AD-14 — Ship-set: declared, per wrapper, in the same PR. (BINDING — inherits ADR-1357 AD-14.)

Each new wrapper is either added to `scripts/framework/framework_consumer_files.txt` (with its L2 module and any `scripts/automation/lib/` import, and a `technical-design`-verified post-install import path) **or** declared HOS-repo-only in the agent file that names it. AF-5's existing six-uninstalled-wrapper bug is not to be reproduced; #1542 may leave it unfixed (it is not this issue's) but may not enlarge it.

### AD-15 — The duplicate `codeowners` modules are resolved before either gets a CLI, and the CODEOWNERS surface belongs to #1357. (BINDING — resolves **Q7**.)

Two modules with different glob engines exist (`scripts/oversight/codeowners.py`, `re`-based; `scripts/automation/lib/codeowners.py`, `fnmatch`-based). CODEOWNERS drives the human-approval gate, so a third answer to "who owns this path" is a governance defect. ADR-1357 AD-3 already lists a `codeowners` subcommand on the primitive surface and its AD-4 step 3 runs the gate, so **#1357 owns it**; #1542 exposes no CODEOWNERS CLI. **Binding on #1357's slice:** the duplication is resolved (one authority, the other retired or made a re-export) *before* the subcommand ships. Note the third engine already in the building: `require_human_approval.glob_to_regex`, which `audit_predicate.py` deliberately imports rather than duplicating — that is the pattern to converge on.

### AD-16 — The specialist-subagent audit (NG-4) is a separate v0.7.0 issue, filed now, and it is #1146's prerequisite, not #1542's. (BINDING — resolves **Q8**.)

`coder`, the eight reviewers, `unit-test`, `system-test` and `risk-assessor` run in the same sandboxed session. Their surface is mostly script-shaped already, but `coder`'s git usage lands on AD-7's commit item and `risk-assessor`'s changed-file marshalling is unexamined. Keeping it inside #1542 would be silent scope; leaving it unfiled would surface it during the #1146 rollout as a silent skip. **File it now; sequence it before #1146, parallel to #1542.** (I cannot file it from this session; it is listed in §7 for the orchestrating session.)

### AD-17 — FR-9.3's proof is staged, and a **measurement** gates the final stage. (BINDING — resolves **Q10**.)

Three levels, in order: (1) AD-11's static detector plus AD-10's coverage check, in CI — cheap, continuous; (2) a **replay harness** that takes a recorded cycle's command sequence and evaluates each command against the role's rule set, reporting every command that would not match — this is the artifact that makes "expressible under FR-8" checkable rather than asserted; (3) a **shadow cycle** under the real policy with denials logged and non-fatal, before #1146 flips anything.

**Prerequisite that binds before the allow list is frozen:** per AV-7 and `SANDBOX-POLICY.md` §4 item 7, neither the glob matcher's behaviour nor `autoAllowBashIfSandboxed`'s interaction with the classifier is verified. `technical-design` must produce a **characterization run** in a throwaway clone — a table of candidate command forms against observed allow/deny — before level (2)'s rule-set evaluator is written. Writing a matcher-simulator against an unverified matcher would produce a proof of the wrong thing.

### AD-18 — #1360 is downstream and builds on these surfaces. (BINDING — resolves **Q11**, confirming §3.4.)

The 2026-09-06 comment pointing the other way is superseded by the 2026-09-10 rulings and by the milestones (v0.7.0 vs v0.7.10). #1360's "invert the driver" treats these surfaces as substrate; #1542 keeps FR-6.9 (CI-invocable, non-interactive, no cron-only credential dependency) so the inversion is a relocation rather than a rewrite.

### AD-19 — Enforcement of "no new unallowlistable or uninvocable surface" is mechanical, via AD-11's detector in CI. (BINDING — resolves **Q12**.)

No reviewer is assigned to remember it. The detector plus AD-10's coverage check become required status checks, joining the per-job gates #1571 promoted. #1536's new overseer-issued execution and #1538's audit reshaping are then held to it automatically, with no coordination between the issues.

### AD-20 — Audit reads and writes stay #1538's; #1542 builds no audit CLI and blocks rather than forks. (BINDING — **Q2**/CR-1 unchanged.)

The requirements document's §3.3 stands and ADR-1357 AD-10 already declared the same named dependency. **One addition:** if a #1542 slice reaches a point where it needs a filtered audit read and CR-1 has not landed, that slice **blocks on #1538** — it does not build a parallel read path "temporarily." A temporary second audit reader is how a system acquires two answers to "did this already happen," and the #849 class is precisely a wrong answer to that question.

---

## 3. Escalations — held for the human

### ESC-1 — Activating the worker lifecycle controls (AV-6). *Product boundary: autonomous behaviour, throughput, first-ever execution.*

Seven controls — idempotency precheck, failure-cap breaker, claim/heartbeat, triage routing, budget gate, envelopes, ledger — are instructed in `worker.md` and have **never executed**, because no invocation form exists. Building AD-6's surface turns them all on at once. The observable consequences: issues can now be **budget-gated** and labelled `hos-budget-gated`; a cid with repeated failures becomes **poisoned** and the worker exits; security-classified issues route to **embargo**; low-confidence triage routes to `needs-human`. Each is a designed behaviour the human approved in #254 — but it takes effect for the first time, in an autonomous loop, all at once.

**Options:** (a) build the surface and activate; (b) build it in shadow mode first — record what each control *would* have decided alongside what the cycle actually did, then activate (this is ADR-1357 slice 3's pattern, and it produced the argument for that ADR's whole approach); (c) do not activate — in which case AD-6 binds the alternative: **delete the narration from `worker.md`**, because seven fictitious instructions are worse than none.

**My recommendation: (b), then (a).** The shadow window costs one cycle-configuration change and converts an assumption into a measurement, exactly as it did for #1357. **I have not bound it**: it changes what the autonomous worker does to real issues, which is the product-boundary checkpoint, not architecture.

### ESC-2 — What enforcement posture will the autonomous roles actually run under? (AV-7.) *Deployment topology; determines whether FR-8 is a control or a record.*

Three facts, one of which I could not resolve: (i) the tracked template sets `autoAllowBashIfSandboxed: true`, and `SANDBOX-POLICY.md` §3 describes the allow list as *"about intent and auditability more than about hard enforcement"*; (ii) the same template's `disableBypassPermissionsMode: "disable"` **blocks `bin/hos-cron:1764`'s launch line outright** — `SANDBOX-POLICY.md:96-99` states this conflict must be resolved one way or the other and "cannot be both"; (iii) measured in this session on a clone running that very policy, unmatched Bash calls *are* denied — but not on any clean syntactic rule.

**Decisions that are yours:** does the autonomous policy keep `autoAllowBashIfSandboxed: true` (containment by filesystem/network boundary, allow list as audit record) or set it `false` (allow list as hard gate)? And does `hos-cron` stop passing `bypassPermissions`, or does the autonomous policy omit `disableBypassPermissionsMode`?

This is formally #1146's to decide, and I have bound **AD-13** (design for the strict posture regardless) so that #1542 is not blocked by it — script coverage is necessary under the strict posture and beneficial under the permissive one. But the *acceptance bar for #1542* ("never prompts at all") is not measurable until it is answered, and the honesty requirement in AD-13 depends on it directly. **Raising it here so #1146 inherits a question, not a surprise.**

### ESC-3 — May parallel v0.7.0 work keep adding agent-instructed library calls before the detector lands? (AV-5.) *Process policy; no correct technical answer.*

On 2026-09-11, one day after ADR-1357 merged, #1580 added a new public `merge_authority.py` function plus `overseer.md` prose instructing *"Call `check_required_content_checks(…)` on every cycle"* — a new instance of the exact defect, in the exact file, while the fix for it was in design. It was a correct and well-reasoned fix to a real routing bug; the defect was in *how the control was made reachable*, which nothing in the pipeline checks today.

**Two consequences, one of which needs you.** The technical consequence I can bind: AD-11 gives the detector this rule, and it lands first. The process question I cannot: **until that detector is required in CI, is v0.7.0 work permitted to land new "call this function" prose?** Options: (a) no — such work must ship an invocable surface or hold; (b) yes, but each instance is recorded in the AD-11 baseline with a named owner; (c) no policy, rely on the detector when it arrives.

**Recommendation: (b)** — it neither stalls in-flight bug fixes nor lets the debt go unrecorded, and the baseline is already the mechanism.

**One binding note for #1357's `technical-design`, which is not an escalation:** ADR-1357's AD-4 internal sequence predates #1580 and therefore omits step 4c (the required-content-checks bounce gate, which `overseer.md` now says must run **before** the CODEOWNERS and protected-surface gates). The decision surface must fold it in, or it will ship with a gate missing that its own source document requires. This is an ADR-1357 amendment and should be annotated on #1357, not absorbed silently here.

---

## 4. Build order

Detector first (AV-5), then reads, then retrofits, then the compound builds, with the behaviour-changing and policy-gated slices isolated at the end. Slices 1–4 are unblocked today and remove the majority of the raw-construct sites.

| # | Slice | Contents | Gate to proceed |
|---|---|---|---|
| **1** | **Detector + inventory baseline** | AD-11's document scanner (incl. the call-a-function rule) + AD-10's three-way coverage check, both in CI with an enumerated, closed debt baseline; FR-9.1's re-audit of the "already covered" table against *"invocable with literal arguments?"* | Detector red on today's four documents with every failing site enumerated; check green; no new baseline entries permitted after merge |
| **2** | **PR-read library + read CLI** | AD-2's residual `github.py` functions (events, labels, merged-with-`merged_by`, branch protection); `bootstrap/query_prs.sh` named operations; `query_issues.sh --comments --contains/--author` | Every FR-1 answer obtainable from one literal-argument call; baseline shrinks by the `gh api` sites in `worker.md`/`overseer.md`/`overseer-cron-prompt.md` |
| **3** | **Self-derivation retrofits + cheap single-calls** | AD-4 on `check_pr_reviewed.sh` (`--pr`), `pr_readiness.py` (derive `--cid`/SHAs); G10 identity assertion; G11 next-candidate; G7 merged sweep; G4 release tier | `overseer-cron-prompt.md:30` loop and `worker-cron-prompt.md:101` `$(cat …jq)` both deleted; all four `$VAR` identity-guard/`cd` sites replaced |
| **4** | **Commit path** | G1 `commit_work.sh` with the shared trailer validator; `commit_onto_base.sh` delegates to it; **#1552 resolved**; `git add`/stash handling (AV-10) | A worker commit is one literal call; #1552 either no longer prompts or is documented as a deliberate authorization gate with that stated in its header |
| **5** | **Validator/release verdicts** | G2 §3b ancestry verdict; VF-8 committed-state adapter over `release_artifact_logic.py` (purity preserved); G6 release-results composer | Each emits one record; no chained git reads remain in either cron prompt |
| **6** | **NG3b authorization verifier** | G5 R1 + R5 + composed `status`, with per-condition evidence | Hand-evaluation of one real release request compared field-by-field against the verdict — the last time a human evaluates NG3b by reading it |
| **7** | **Branch-surgery safety items** | G12 dirty-PR rebuild (sharing `submit_pr.sh`'s ownership precheck — closes the #1162 residual force-push path); G13 out-of-scope commit handling | Reviewed as a safety change, not an allowlisting change; own PR |
| **8** | **Worker lifecycle** | AD-6's `worker_admit.py` + `worker_claim.sh` / `worker_release.sh` / `worker_lifecycle.sh`, **or** the `worker.md` narration deletion | **Blocked on ESC-1.** If (b), lands in shadow mode first and the divergence is measured |
| **9** | **FR-8 artifact + generator** | AD-9's two role templates; `gen_sandbox_config.py` accepts all three roles; AD-17's characterization run, then the replay harness; ship-set (AD-14) | **Gated on ESC-2** for the posture and on slices 1–8 for the content. Protected-surface PR (`contract/**`) — human-gated regardless |

Slices 1–7 are independently valuable and unblocked. If ESC-1/ESC-2 stall indefinitely, slice 1 alone converts "the autonomous roles emit unallowlistable constructs" from a claim into a continuously-measured number, and slices 2–4 remove most of them.

---

## 5. Non-goals — named, with owners

- **The merge-authority surface, including all PR writes** — #1357 (AV-3, AD-5). #1542 audits and sweeps prose; it builds none of it.
- **Audit logging, read or write** — #1538, with CR-1 as the standing constraint (AD-20).
- **CODEOWNERS CLI and the duplicate-module resolution** — #1357 (AD-15).
- **Turning the sandbox on** — #1146/#1053. This issue removes the reasons it would break the roles; it flips nothing.
- **Filesystem and network scoping** — #1146. This issue covers the Bash surface only.
- **`bin/hos-cron` itself** — outside the session; permission rules never apply to it. Its pre-computed context is a mitigation to lean on, not to re-derive. The *prose it injects* is in scope (FR-7).
- **The specialist-subagent surface** — its own v0.7.0 issue (AD-16), sequenced before #1146.
- **#1360's driver inversion** — v0.7.10, downstream (AD-18).
- **Rewriting any decision logic** — reachability only, with the sole exception of AD-15's duplicate-authority resolution, which is #1357's.

---

## 6. Startup-gap analysis and affected sign-offs

**Should this have been settled in an initial architecture review?** Yes, and the gap is structural rather than incidental. Three subsystems — `merge_authority.py` (#1357), the #254 worker lifecycle modules (AV-6), and `codeowners.py` — were each built as libraries with no invocation surface, while the agent documents that consume them were authored as *"call `function(...)`"* instructions to an agent whose only capability is issuing shell commands. Nothing in the design phase asked *"what invokes this?"* The lesson attaches to the design phase, not to any individual fix, and belongs in #1243's core-principles register alongside #1359's *"use the code, don't roll it yourself"*: **a control must be executable by the actor instructed to execute it, and the design must name the invocation.**

**Is this a revision of a prior ADR of mine that orphans sign-offs?** No. ADR-1357 is **extended and inherited here, not superseded** — AD-1 adopts its contract, AD-5 defers to its AD-5, AD-15 assigns it the CODEOWNERS surface. No decision of ADR-1357 is reversed, so no design or code approved against it is orphaned. The one amendment ADR-1357 needs (AD-4's missing step 4c, per AV-5) is a *completion* forced by work that landed after it, and it is routed to #1357's own `technical-design` rather than applied here; nothing has yet been built against ADR-1357, so there are no sign-offs to invalidate.

**Prior sign-offs that stand.** All existing library unit tests and their sign-offs stand — this ADR changes no library semantics. `#1580`'s sign-offs stand as a *routing* fix; what it lacked was an invocation surface, and AD-11's detector is the forward control, not a retroactive invalidation.

**What is orphaned, and it is not a register entry.** Every worker cycle's claim, breaker, budget and triage step since the #254 modules shipped was narrated, not executed (AV-6). These are not §3-register sign-offs, so nothing in the register is invalidated — but they are **unaudited outputs of controls believed to be running**, the same condition ADR-1357 recorded as ESC-3 for the overseer. I record it here rather than let it pass and fold its disposition into **ESC-1**: if the human chooses (c) *do not activate*, the honest conclusion is that these controls never existed, and the documents must stop saying they do.

---

## Human Review Required

**RISK: MEDIUM.** **CONFIDENCE: HIGH** on §0 (every finding re-derived from `origin/main` @ `511e2a2f` via `git show`/`git grep`, with the three gaps stated). **HIGH** on AD-1 through AD-5 and AD-9 through AD-15, which follow from binding rulings and verified facts. **MEDIUM** on AD-6's shape, which depends on ESC-1's answer. **LOW** on inventory completeness — AV-10 already found uninventoried sites (`git add`, `git stash`, four `$VAR` guard/`cd` lines), and FR-9.1's re-audit is expected to grow it further, not shrink it.

**Change classification: `structural`** — AD-5 removes a delivery family from this issue (it moves to #1357), AD-6 makes the worker lifecycle's *activation* an explicit decision rather than an implementation detail, and AD-11 re-sequences the detector from an acceptance criterion to the first slice.

**Three items for you (§3):**

1. **ESC-1 — worker lifecycle activation.** Activate, shadow-then-activate, or delete the narration? Recommendation: **shadow, then activate.** Blocks build slice 8.
2. **ESC-2 — the autonomous roles' enforcement posture** (`autoAllowBashIfSandboxed`, and `disableBypassPermissionsMode` vs. `hos-cron`'s launch line). Formally #1146's; needed before slice 9 and before FR-8's artifact can describe itself honestly.
3. **ESC-3 — may in-flight v0.7.0 work keep adding "call this function" prose before the detector is required?** Recommendation: **yes, but every instance is recorded in the AD-11 baseline with an owner.**

**Two items for the orchestrating session, not decisions:** file the specialist-subagent audit issue (AD-16), and annotate #1357 with the AD-4 step-4c amendment (§3, closing note).

**Not escalated, because already ruled:** the layered-CLI granularity question (**Q1** — ruled on #1542, 2026-09-10, and bound by ADR-1357), and the decision-record precondition (**Q6** — superseded by ADR-1357 AD-5, which prohibits the mechanism the question proposed).
