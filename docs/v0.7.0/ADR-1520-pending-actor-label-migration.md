# ADR-1520: Pending-actor label migration. `needs-ai` becomes `needs-worker`, and `needs-overseer` is added, through provision-first, a dual-read window, a human-run relabel, and a measured close

**Status:** ACCEPTED FOR DESIGN. Binds `technical-design`, `coder` and the reviewers. **Two items are held
for the human** (§6). ARCH-ESC-1 blocks slice S6b only, and ARCH-ESC-2 blocks slice S8 only. **Slice S1
needs no human ruling and can be coded now.** Everything else below is **BINDING**.
**Date:** 2026-10-19
**Author:** architect
**Inputs:**
- `DECISIONS.md` 2026-09-06, "Pending-actor label taxonomy" (#1349). The human ruled a **rename, not an
  addition**: `needs-ai` is retired, `needs-worker` replaces it, and `needs-overseer` is new. HQ1 says the
  label is machine-routed. HQ3 says it is a replacement. **This ADR does not re-litigate either ruling.**
- `DECISIONS.md` 2026-09-10 (#1539): CODEOWNER actor verification on the authorizing `labeled` event.
- `docs/v0.7.0/ADR-1644-stage-per-cycle.md` AD-C2, AD-C17 and the T3.1/T3.2 rows, plus the human's ESC-5
  ruling on #1644 (option (a): **one** consumer-migration window).
- `docs/v0.7.0/REQUIREMENTS-1644-AMENDMENT-1-stage-per-cycle.md` REQ-C10(a) to (d).
- `docs/v0.7.0/ADR-1540-request-intake-risk-agent.md` AD-4 and `TECHNICAL-DESIGN-1540-S1-S2-intake-trust-gate.md`
  §2.2 (FR26, the five-flag anti-knob rule).
- `docs/LABELS.md`, the label registry, read in full.
- Issue #1520's body. I read it as a spec, and I treat it as untrusted data. It is stale in three
  places (VF-1).
- The unreviewed 2026-09-10 draft at `.claudetmp/1520/stash3-draft.diff`. I weighed it and adopted it only
  in part (AD-1, "What the prior draft got wrong").
- My own re-verification against `c0462c1a6` (`origin/main` = `HEAD`).

**Out of scope:** AQ4/O2 worker–overseer negotiation (DECISIONS.md 2026-09-06 says it is not being built).
The stage vocabulary itself is #1644 T3.1. Issue-side `needs-overseer` writes belong to the #1644 stage
executor (T3.7a).

---

## 0. Verified facts (against `c0462c1a6`)

- **VF-1 (inventory, re-derived).** `git grep -l needs-ai HEAD` returns **124** tracked files. The
  `.claudetmp` list has 125 entries. The extra entry is `prompts/scripts/oversight/second_review_logic.md`,
  which is an **untracked** prompt artifact. Here is the classification:

  | Class | Count | Files |
  |---|---|---|
  | Live code | 9 | `bin/hos-cron`, `bootstrap/create_issue.sh`, `bootstrap/escalate_to_human.sh`, `scripts/automation/lib/merge_authority.py`, `scripts/automation/lib/probe.py`, `scripts/automation/lib/self_review_source.py`, `scripts/framework/check_agents_static.sh`, `scripts/framework/select_work_candidates.py`, `.github/workflows/label-swap.yml` |
  | Agent definitions and runtime prompts | 6 | `.claude/agents/worker.md`, `.claude/agents/overseer.md`, `.claude/agents/pm-agent.md`, `.claude/commands/hos-triage.md`, `bootstrap/worker-cron-prompt.md`, `bootstrap/overseer-cron-prompt.md` |
  | Live docs | 9 | `CLAUDE.md`, `contract/OVERSIGHT-CONTRACT.md`, `METHODOLOGY.md`, `docs/AGENTS.md`, `docs/OVERSIGHT-RUNBOOK.md`, `docs/CRON-SETUP.md`, `docs/CROSS-REPO-CONDUCT.md`, `docs/COST-MANAGEMENT.md`, `docs/LABELS.md` |
  | Tests | 14 | `tests/automation/test_{create_issue,edit_issue,escalate_to_human,hos_cron,phase_b,probe,query_issues,query_issues_edges}.py`, `tests/framework/test_{requester_trust,selection_call_sites,select_work_candidates,select_work_candidates_ghshim,select_work_candidates_native}.py`, `tests/oversight/test_agents_static_logic.py` |
  | Historical or non-normative (never edited by this migration) | 86 | `docs/v0.4.0/**` (5), `docs/v0.6.0/**` (13), `docs/v0.7.0/**` (45), `docs/specs/**` (9), `docs/releases/**` (1), `research/**` (5), `prompts/**` (5), `DECISIONS.md`, `docs/issue-reference-2026-06-18.md`, `docs/planning/ENHANCEMENT-IDEAS.md` |

  #1520's body is stale on three points:
  - It names `next_candidates.jq`. That file was **deleted** by #1540 S2, and
    `tests/framework/test_selection_call_sites.py:44-46` asserts that it is gone.
  - It omits `scripts/framework/select_work_candidates.py`. That is the **primary** reader today
    (`--label` default `"needs-ai"` at `:193`).
  - It lists `prompts/AGENTS.md` as live. That file is a prompt-provenance artifact ("Prompt Artifact —
    AGENTS.md", #1317), so it is historical. All of `prompts/**` is historical.
- **VF-2 (selection).** `select_work_candidates.py` queries exactly one label (`list_endpoint`, `:839-843`).
  `EXCLUDED_LABELS = ("needs-human",)` is at `:111`, `LIST_PAGE_BOUND = 5` at `:112`, and the request
  budget is 100 at `:126`. TD-1540 §2.2 pins the flag set at exactly five, and `--label` is one of them.
- **VF-3 (authorization predicate).** `requester_trust.verify_codeowner_actor` (`:614-645`) accepts one
  `label_name`. It collects every `labeled` event for that name, walks them newest-first, skips bot actors
  (`:641`), and returns the first CODEOWNER human. It **does not** consider `unlabeled` events. A bot
  re-label after a CODEOWNER's act therefore does not erase that act, which is residual **R-3** (`:630`).
  `probe.py:300-329` delegates to the same predicate. The selector calls it at `:606`.
- **VF-4 (probe).** `probe.py:404-445` (`STRATEGY_MILESTONE`) queries `labels=needs-ai` and verifies
  `"needs-ai"` at `:437`. It has no live caller outside `multi_customer.py`'s consumer fan-out
  (DECISIONS.md 2026-09-10). When it is used, it reads **consumer** repos, and those may be on either
  label.
- **VF-5 (PR routing is overloaded, and it contradicts itself today).**
  - `bin/hos-cron:1208` routes `draft ∧ needs-ai` to `needs-fix-bounce`.
  - `:1222` routes `needs-ai ∧ ¬needs-human` to `needs-fix`.
  - But `.claude/agents/worker.md:156` and `docs/AGENTS.md:244-246` tell the worker to label **its own
    newly opened PR** `needs-ai` to "hand off to the overseer". `:1222` reads exactly that label as
    "worker, fix this".
  - The same label therefore means "overseer's court" to one writer and "worker's court" to its reader.
    The autonomous path does not hit this, because `bootstrap/submit_pr.sh` writes no label. The
    interactive path does hit it.
- **VF-6 (writers).**
  - `merge_authority.py:634` writes `needs-ai` on a non-PROCEED, non-ESCALATE oversight verdict.
  - `record_pr_bounce` takes `label="needs-ai"` (`:1268`) and adds it via REST `POST …/issues/{n}/labels`
    (`:1310-1314`).
  - `self_review_source.py:229` passes `--field labels=["hos-coordination","needs-ai"]`. I **suspect**
    this is a pre-existing defect: gh's `--field` does not parse JSON arrays. I did not verify it.
  - `bin/hos-cron:1085,1823,1898,2194` file issues with `gh issue create --label …needs-ai… 2>/dev/null`.
    Any failure there is **silent**.
  - `label-swap.yml:109` runs `gh issue edit --remove-label needs-ai --add-label needs-human … || true`.
  - `edit_issue.sh:203` and `escalate_to_human.sh:326` use REST label-add. `create_issue.sh:118` uses
    `gh issue create`.
- **VF-7 (no provisioning exists).** I searched `scripts/`, `bootstrap/` and `bin/` for `gh label`,
  `label create` and repo-level `POST …/labels`. I found **nothing**. The only label writes are per-item
  adds. `hos_install.sh:2550` applies `needs-human` to its own upgrade PR on a best-effort basis.
  `docs/LABELS.md` "Known gaps" agrees.
- **VF-8 (the registry loader exists now).** `scripts/automation/lib/dimension_registry.py` is ADR-1643
  AD-9's schema-parametric loader. Its `KINDS` table is at `:102`, and its header says "A future kind adds
  one `KINDS` row and one handler module". The installer mirrors that table at `hos_install.sh:2146`
  (`_REGISTRY_KINDS`), and `tests/framework/test_install_registry_data.py:159-166` pins the mirror.
  **ADR-1644 VF-C10's "the loader does not exist" is now stale.**
- **VF-9 (consumers run their own copy).** `bin/hos-cron` takes `REPO_ROOT` from `projects.conf`
  (`${ROLE}_root`, `:187`). An upgrade arrives as a draft PR in the consumer repo
  (`hos_install.sh:2537-2551`). A consumer's **code** therefore flips when that PR merges. Its **labels**
  do not flip.
- **VF-10 (dedup queries filter on the pending-actor label).** `overseer.md:161` and
  `overseer-cron-prompt.md:38` look for an existing process-gap issue with `--label needs-ai`. During any
  label transition, that misses issues filed under the other name and files duplicates. `bin/hos-cron`
  already learned this lesson (#1496, `:1798-1806`: it dedups on the title prefix, not on labels).
- **VF-11 (doc drift).**
  - `overseer.md:810-812` tells the overseer to adapt to a consumer's `needs_ai` variant.
    `docs/LABELS.md:13-18` says such variants are unsupported.
  - `docs/LABELS.md` cites `merge_authority.py:633/:1223`. The lines are now `:634/:1268`.
- **VF-12 (create-on-apply was not measured).** Measuring it needs a GitHub mutation, which this cycle may
  not perform. My belief, which **no decision below depends on**:
  - REST `POST /issues/{n}/labels` auto-creates an unknown label with no description.
  - `gh issue create --label` and `gh issue edit --add-label` resolve names client-side and fail.
- **VF-13 (unbuilt designs that pin the old literal).**
  - TD-1644-T3.0b pins `BOUNCE_LABEL = "needs-ai"` (`:240`, rows C3/C4).
  - TD-1604 §1.1 proposes `scripts/automation/lib/hos_labels.sh` with `HOS_LABEL_AI="needs-ai"`.
  - Neither is built. Neither `hos_labels.sh` nor `labels.py` exists.

---

## 1. The problem in one paragraph

A rename has three things that move independently:
1. Code in this repo, which moves when a PR merges.
2. Code in each consumer, which moves when that consumer's upgrade PR merges.
3. Live labels on open issues and PRs in every repo. Nothing moves these automatically.

Human muscle memory is a fourth writer. A bare rename lets these drift apart, and the failure is
**silent**: the selector reports `complete=yes` over an empty list. A second, subtler hazard is
**authorization**. Authorization is a CODEOWNER `labeled` event *for a specific label name* (VF-3). So:
- A relabel either strips every untrusted-authored issue of its authorization (fail-closed, but work
  stops), or
- run under a CODEOWNER's personal token, it **mints** a fresh authorizing event on every issue it
  touches, including issues no human ever approved.

The design has to rule out both.

---

## 2. Decisions

### AD-1: The strategy is a combination: provision first, a dual-read window, a writer switch, a human-run relabel, a measured close, and a permanent tripwire.

The phases, in this order:

| Phase | What | Where |
|---|---|---|
| P0 | Registry data, a provisioning tool, a conformance test. No behavior change. | S1 |
| P1 | Provision `needs-worker` and `needs-overseer` **in this repo** | H-1 (human) |
| P2 | **Readers** accept `needs-worker ∪ {needs-ai}` on issues and on PRs, and authorization honours both names | S2a, S2b |
| P3 | **Writers** emit `needs-worker`/`needs-overseer`. Agents and docs follow. | S3a, S3b, S4, S5 |
| P4 | Relabel this repo's open items. Ship the window-open release to consumers. | S6a, H-2, H-3, S6b |
| P5 | Close the window. The legacy *list* read becomes a one-request tripwire. The authorization alias stays. | S8 |

**Rejected alternatives:**
- **Bare coordinated cutover.** It produces the silent empty queue #1349 named, both for consumers and
  for this repo's own cron in the gap between the merge and the relabel.
- **Relabel script alone.** It has the same gap. A consumer that merges its upgrade but has not yet
  relabeled sees zero work, and nothing says so.
- **An open-ended dual-read.** Two dialects would live forever, and the draft's own open question (2) was
  unanswered.
- **Renaming the GitHub label object (`PATCH /labels/needs-ai`).** Rejected for four reasons:
  1. It rewrites the label on every **closed** issue as well. That retcons the historical record
     DECISIONS.md 2026-09-06 says must not be touched.
  2. It deletes the `needs-ai` label that un-upgraded code still queries.
  3. It collides (422) with a `needs-worker` that has already been provisioned.
  4. It leaves no per-item record.

  For the same reason (1), **`needs-ai` is never deleted** from any repo. Deleting it strips it from
  closed issues.

**What the prior draft got wrong.** Dual-read was right. Everything around it was wrong or has gone stale:
- It patched `next_candidates.jq` and a `bin/hos-cron` query that #1540 S2 has since replaced with
  `select_work_candidates.py`.
- It left authorization on a single label name. Every migrated untrusted-authored issue would have been
  gated, or laundered if a human ran the relabel under a personal token.
- It had no close criterion and no provisioning.
- It deferred the PR side, which is where the semantic overload (VF-5) actually lives.

### AD-2: Ordering. Provision before any write, read before any write, and drop a read last.

- **R1.** No code path emits a label before that label is provisioned in the repo it writes to.
  - In this repo, H-1 precedes the merge of S2a, S2b and every later slice. S2a's list query must never
    be the first thing to touch an unprovisioned name, because VF-12 is unmeasured.
  - In consumers, provisioning happens at install time, *before* the upgrade PR merges (AD-10).
  - The fallback is the `check` preflight (AD-7).
- **R2.** A reader drops `needs-ai` only when no writer can still emit it. That means no code in any
  supported consumer, and no human acting from habit (AD-11). Until then, the reader accepts both names.
- **R3.** The window covers **both** issues and PRs. A bounced draft PR that carries `needs-ai` at cutover
  must still route to `needs-fix-bounce`. Otherwise the #1350 bug comes back for in-flight PRs.
- **R4.** Agent prose (S4) and code writers (S3) may land in either order *after* P2. During the window a
  mix of writers is harmless, by construction.

### AD-3: Semantics. There are three courts. `needs-human` overlays the others. Precedence is fixed.

| Label | On an issue | On a PR |
|---|---|---|
| `needs-worker` | The worker's court. It is the **only** eligibility and authorization carrier (REQ-C10(a), unchanged from `needs-ai`). | The worker must act: an overseer bounce, a CONDITIONAL verdict, or a human hand-back. |
| `needs-overseer` | The overseer's court: the issue's artifact PR is awaiting the overseer. **Writer:** the #1644 stage executor (T3.7a, AD-C2). #1520 adds no issue-side writer. **Not listed by the selector** (AF-C3). | The worker has handed off and the overseer should act. **Writers:** `submit_pr.sh` on PR creation; the worker after it pushes a fix. |
| `needs-human` | Unchanged. Excluded from selection, and it overrides everything. | Unchanged. A hard merge block. |

Five rules apply to all three labels:
- **Invariant.** An item carries at most one of `needs-worker`/`needs-overseer`. `needs-human` is an
  overlay. Escalation never removes the pending label (`escalate_to_human.sh:29` is unchanged in
  substance).
- **Read precedence.** `needs-human` > `needs-worker` > `needs-overseer`. If an item carries both of the
  last two, the reader treats it as the worker's court. One extra worker cycle is cheap. An overseer
  waiting forever on a PR nobody routes is not.
- **Swap order.** Add the target label, then remove the source label. A failed remove leaves both labels,
  and the precedence rule resolves that. The next writer retries, and the operation is idempotent.
  Remove-first is rejected, because a failed add would leave an issue in **nobody's** court, which is an
  invisible stall.
- **The overseer's PR selection does not become label-gated.** It still takes every open, non-draft,
  non-conflicting PR (`bin/hos-cron:1319`). Gating it on `needs-overseer` would add a new silent-skip
  path. On the PR side, `needs-overseer` is a visible and queryable court marker (HQ1). Its only routing
  effect is AD-4's: it is **never** a fix signal.
- **Dedup and lookup queries never filter on a pending-actor label** (VF-10). They match on title or audit
  record, as #1496 does.

### AD-4: The PR routing mapping. Behavior is preserved, and the VF-5 contradiction is removed.

| Today | After #1520 (window: `W` = `{needs-worker, needs-ai}`) |
|---|---|
| The worker labels its own new PR `needs-ai` (`worker.md:156`) | The writer adds `needs-overseer` |
| `record_pr_bounce`: adds `needs-ai`, then converts to draft | Adds `needs-worker`, removes `needs-overseer`, then converts to draft |
| `merge_authority.py:634` CONDITIONAL → `needs-ai` | → `needs-worker` |
| A human hand-applies `needs-ai` to a non-draft PR (#1522) | The human applies `needs-worker`. During the window, `needs-ai` still works. |
| The worker clears `needs-ai` after pushing a fix (#1526) | The worker swaps `needs-worker` → `needs-overseer` (AD-3 order). During the window, it also removes `needs-ai`. |
| `hos-cron:1208` `draft ∧ needs-ai` → `needs-fix-bounce` | `draft ∧ (labels ∩ W ≠ ∅)` → `needs-fix-bounce` |
| `hos-cron:1222` `needs-ai ∧ ¬needs-human` → `needs-fix` | `(labels ∩ W ≠ ∅) ∧ ¬needs-human` → `needs-fix` |
| (none) | `needs-overseer` alone has no fix effect. The PR falls through to the existing review-state checks. |

The pending-actor sets live in one Python module, `scripts/framework/pending_actor_labels.py` (protected).
It holds `WORKER = "needs-worker"`, `WORKER_LEGACY = ("needs-ai",)`, `OVERSEER` and `HUMAN`. Python
readers import it. `bin/hos-cron` carries the literals, and AD-8 ties them to the registry.

**Cross-ADR (TD-1644-T3.0b).** Whichever of S2b and T3.0b lands second carries the adaptation. The
classifier's `BOUNCE_LABEL` becomes the `W` set imported from `pending_actor_labels.py`. C3 and C4 keep
their positions, and `needs-overseer` gets no row of its own. This is a mapping delta, not a behavior
change. T3.0b's TD gets a delta re-check, not invalidation (§5).

### AD-5: Authorization survives the rename. The predicate takes a name *set*, the alias is permanent, and the relabel can only run as a bot.

- `verify_codeowner_actor` changes from `label_name: str` to `label_names: frozenset[str]`. It matches a
  `labeled` event whose label name is in the set. Nothing else changes: bots are still skipped, the actor
  must still be a CODEOWNER human, and the scan still walks newest-first over all history. Callers pass
  `{WORKER} ∪ WORKER_LEGACY`.
- **The alias is permanent and is not removed at window close.**
  - Historical `labeled needs-ai` events by a CODEOWNER are immutable records of real human acts.
  - Honouring them adds no principal and no path that R-3 does not already accept. Today, a CODEOWNER
    `needs-ai` act followed by a bot re-adding `needs-ai` authorizes. After the rename, a CODEOWNER
    `needs-ai` act followed by a bot adding `needs-worker` authorizes. These are the same exposure.
  - Dropping the alias would silently un-authorize every migrated untrusted issue. That is fail-closed,
    but it spends human acts for nothing.
  - The alias also makes the design independent of VF-12's unknown, which is whether GitHub rewrites
    event label names.
- **No bot self-authorizes (#1539).** Every bot writer stays non-authorizing, under either name:
  `github-actions[bot]` (label-swap), the worker's Step 0 triage, `create_issue.sh`, and the migration
  tool.
- **The relabel cannot launder authorization.** The migration tool (AD-9) mints its token **only** through
  `bootstrap/get_app_token.sh --app <role>`, using the `edit_issue.sh` pattern. It refuses to run unless
  `HOS_BOT_LOGIN == HOS_EXPECTED_BOT_LOGIN` **and** `is_bot_reviewer(HOS_BOT_LOGIN, …)` is true. It has
  **no** personal-token path. A bulk relabel under a CODEOWNER's own login would turn every gated issue
  into an authorized one. This rule exists to make that impossible.
- **Required negative tests (S2a, S6a).** Every one of these must pass:
  - **T-A1.** A bot-applied `needs-worker` on an untrusted issue with no CODEOWNER act is gated.
  - **T-A2.** A CODEOWNER `needs-ai` act followed by a bot swap to `needs-worker` is authorized.
  - **T-A3.** A CODEOWNER `needs-worker` act is authorized.
  - **T-A4.** A non-CODEOWNER human `needs-ai` act is gated.
  - **T-A5.** A `milestoned` event still never authorizes (AR-7).
  - **T-A6.** The migration tool refuses a non-bot token identity.
  - **T-A7.** The selector's flag set is still exactly five (TD-1540 §2.2). The alias is a module
    constant and never a flag.

### AD-6: Dual-read mechanics in the selector and the probe.

- **Defaults.** `--label` defaults to `needs-worker`. When the given label is `WORKER` or one of
  `WORKER_LEGACY`, the selector queries the **whole group**: one paginated list per name, each under the
  existing `LIST_PAGE_BOUND`. It unions them by issue number **before** D1, so D1, D2 and later run once
  over the union.
- **Bounds and failures.**
  - Both fetches draw on the one `_Budget`.
  - Either fetch reaching its bound sets `list_truncated`.
  - Either fetch returning `FAILED` gives `list-query-failed` (exit 2, fail-closed, as today).
  - Either fetch returning `REFUSED` takes the existing "does not walk a partial list" path.
  - GitHub's `labels=` filter is AND, so one query with two names would be wrong.
- **Cost.** At most +1 request per cycle while the legacy list is small (≤100), and never more than
  +`LIST_PAGE_BOUND`. That fits the 100-request budget.
- **Measurement.** The selector's report gains `legacy_label_records=<n>`, the number of records reached
  only through a legacy name. This is the window's measurement (AD-11). S2b's `bin/hos-cron` logs it and
  writes a `legacy-label-present` audit event when `n > 0`.
- **The probe** gets the same treatment: two queries, a union, and the predicate's set.
- **After the window closes (S8).**
  - The legacy *list* read is replaced by a **tripwire**: one request per cycle
    (`labels=needs-ai&state=open&per_page=1`, repo-wide). Its cost is bounded at ≤1% of the budget.
  - It stays **permanently**, because a consumer can skip releases.
  - If the tripwire hits: the selector emits a `legacy-label-present` WARN line, and does **not** select
    the item.
  - If the `needs-worker` set is also empty, it exits **3 (DEGRADED)** with reason
    `legacy-label-unmigrated`. That is AM-32's "unknown, not none" contract. It is never an empty-queue
    claim.

### AD-7: Registry and provisioning: one registry kind on the existing loader, one tool, additive only.

- **The data.** `contract/labels/core.yaml` is a new **kind**, `hos.label-registry`, on
  `dimension_registry.py`'s engine. It needs one `KINDS` row, one handler module
  (`scripts/automation/lib/label_registry.py`) and the mirrored `_REGISTRY_KINDS` installer row (VF-8).
  That honours ADR-1643 AD-12/ADR-1644 SEAM-1's "one loader".
  - It is **CORE-only.** A PACK or PROJECT layer may not add, remove or rename an entry, because label
    names are fixed literals (`docs/LABELS.md:9-18`).
  - It lives under `contract/**`, so it is protected and the installer ships it. `docs/LABELS.md` is not
    shipped.
  - `docs/LABELS.md` stays the **one human registry**. The conformance test enforces a bijection between
    the YAML and the doc's rows (AD-8). The result is one registry with a data half and a prose half, not
    two registries (REQ-C10(c)).
- **Each entry carries:** `name`, `status ∈ {active, planned, legacy-read, retired}`, `color`,
  `description`, `writers[]` and `readers[]` (repo paths), and an optional `provision: false`. Use that
  for labels that must never be created, such as `hos-halt`, which is a file and never a label
  (`docs/LABELS.md`).
- **The extension point for #1644 T3.1 is a `families:` section.** Each family has a literal `prefix`
  (for example `stage:`) and a `provider`: a dotted function returning the concrete label specs from its
  own source of truth. T3.1 registers a `stage` family whose provider reads `contract/stages/core.yaml`
  through the same loader. `hos:round-reset` is an ordinary entry. S1 ships the family mechanism with
  **zero** families, plus a test-fixture family. T3.1 adds rows and one provider, and changes no tool
  code. **This replaces T3.1's "provisioning script, conformance test" contents** (§5).
- **The tool.** `scripts/framework/labels_cli.py` (L2, protected) and `bootstrap/provision_labels.sh` (L3,
  fixed argv, pass-through exit codes, per ADR-1643 AD-1/AD-1a).
  > **Erratum (2026-10-20, S1 TD review, TD-1520-S1 §18.2/§18.4).** "Per ADR-1643 AD-1/AD-1a" over-cites
  > the ADR. ADR-1643 §10.4 scopes AD-1a to `invoke_agent.sh`. The wrapper mints and revokes its own App
  > token in the `pr_review.sh` shape, and adopts AD-1a's other rules: the interpreter ladder, no stdout, no
  > JSON, pass-through exit codes. It differs from `pr_review.sh` in one way: it unsets the inherited
  > `GH_TOKEN`, `GITHUB_TOKEN`, `HOS_BOT_LOGIN`, `HOS_EXPECTED_BOT_LOGIN` and
  > `HOS_LABELS_TOKEN_MINT_FAILED` before minting, so it never revokes or uses a caller's token (#2117).
  > Separately, "the installer ships it" (the data bullet above) is wrong for S1: the `_REGISTRY_KINDS`
  > row handles `pack-*.yaml` layers only. S6b ships `core.yaml` and the tooling (TD-1520-S1 §18.3).
  - **`check`** is read-only. It lists repo labels (paginated, bounded) and reports `missing`, and
    `present-unprovisioned` (it exists, but the description or color differs, as an auto-created label
    would per VF-12). Exit codes: 0 when everything is present, 1 when something is missing, 2 on error.
  - **`provision`** does a dry run by default. `--apply` creates **only** missing entries whose status is
    `active`, `planned` or `legacy-read`. It **never modifies, renames or deletes** an existing label,
    because a consumer may have recoloured one. It is idempotent: a second run makes zero writes, and a
    test asserts that. Label creation produces no issue events, so the token identity is irrelevant to
    authorization.
  - Both write a `labels-provisioned` / `labels-checked` audit record.
- **The preflight (S3a).** `bin/hos-cron` runs `check` once per worker cycle (1 request). On exit 1 or 2,
  it logs a loud `LABELS NOT PROVISIONED` line, writes a `labels-unprovisioned` audit event, and puts a
  directive line in the context block. It **does not halt the cycle**. That keeps #1520 from adding a new
  halt mode (product-boundary). The `gh issue create … 2>/dev/null` writers (VF-6) are exactly what this
  makes visible.

### AD-8: The conformance test, with the exclusion list as data and a ratchet for migration progress.

The location is `tests/framework/test_label_conformance.py`. The data lives in
`scripts/framework/label_literal_allowlist.txt`. That file is **protected**, so the exclusion list cannot
be widened without the CODEOWNERS gate. It has three sections:
- `[historical]` holds permanent globs: `docs/v*/ADR-*`, `docs/v*/REQUIREMENTS-*`,
  `docs/v*/TECHNICAL-DESIGN-*`, `docs/v*/PANEL-*`, `docs/v*/SPEC-*`, `docs/specs/**`, `docs/releases/**`,
  `research/**`, `prompts/**`, `audit/**`, `DECISIONS.md` (append-only), `docs/issue-reference-*.md` and
  `docs/planning/**`.
- `[legacy-readers]` holds permanent files that legitimately keep `needs-ai`: `pending_actor_labels.py`,
  `contract/labels/core.yaml`, `docs/LABELS.md`, the migration tool, and the named alias tests.
- `[pending]` is the shrinking ledger: every other file still containing `needs-ai`.

The properties every slice must keep green:
- **P1.** Every label literal in live code, in a recognised **label-bearing shape**, is a registry entry or
  matches a family prefix. The shapes are a list of patterns kept as data in the test: `--label`,
  `--add-label`, `--remove-label`, `labels=` in an endpoint, `labels_to_add=[…]`, `"labels": [`,
  `label: str =`, `EXCLUDED_LABELS`, `_HUMAN_GATE_LABELS`, `KNOWN_LABELS=`, `*" <name> "*` label tests in
  bash, and `default=` on a `--label` argument. `technical-design` fixes the exact patterns.
- **P2.** There is a bijection between registry entries and the backticked first-column names in
  `docs/LABELS.md`'s table.
- **P3.** Every declared `writers[]`/`readers[]` path exists and contains the literal. That catches stale
  claims like VF-11.
- **P4 (ratchet).** `needs-ai` appears only in `[historical] ∪ [legacy-readers] ∪ [pending]`. A
  `[pending]` file that **no longer** contains it fails the test, so each slice must shrink the ledger.
  A **new** file containing it fails too. This is the mechanical form of "no blanket sed": the boundary
  is data, and every crossing is reviewed.
- **P5.** Status consistency:
  - A `planned` label has no live-code reader or writer.
  - A `legacy-read` label has no writer outside `[pending]`.
  - A `retired` label appears only in the tripwire and in `[historical]`/`[legacy-readers]`.
- **P6.** Each P1 pattern matches at least one in-test fixture, so a pattern that rots fails loudly.

`scripts/framework/check_agents_static.sh:170` `KNOWN_LABELS` is a P1 shape. That surfaces its
pre-existing `needs-coordination` misspelling (it should be `hos-coordination`, per `docs/LABELS.md`), and
S1 fixes it. S1 must also add `needs-worker|needs-overseer` there **before** S4. Otherwise the static
check reads them in agent files as unknown agent names.

### AD-9: The live relabel is a tool. It dry-runs by default, preserves behavior, runs only as a bot, and a human runs `--apply`.

The tool is `labels_cli.py migrate`, with the L3 wrapper `bootstrap/migrate_labels.sh` (S6a).
- **Scope.** Open issues **and** open PRs carrying `needs-ai`. Closed items are never touched.
- **Mapping, which preserves behavior.** Each item gets `needs-worker` added and then `needs-ai` removed.
  A non-draft PR carrying `needs-ai` is ambiguous today (VF-5). It maps to `needs-worker`, because that is
  how `hos-cron:1222` routes it today. Such PRs are **listed separately** in the dry-run output for a
  human to re-court by hand. The tool never resolves an existing ambiguity by guessing differently from
  the current code.
- **The partition check.** Before and after `--apply`, the tool runs the selector's partition
  (eligible / gated / excluded) over the affected milestone(s). It writes both to the audit record, and
  any difference is a loud failure. AD-5 says they must be identical.
- **Identity.** It runs only as a bot (AD-5). **`--apply` requires `--app human`.** That is the
  human-proxy App identity, which is a bot, so it is non-authorizing.
- **Durability.** It is idempotent and resumable. Every write is recorded in a `labels-migrated` audit
  event (per item: number, before, after).
- **Who runs it.** The worker and the overseer may run `--dry-run` and `--verify` (read-only). **They never
  run `--apply`.** A bulk mutation of live work-state across a whole repo is irreversible in practice:
  mixed later writes make a clean reversal impossible. It is therefore human-initiated:
  - the human runs it, or
  - the human-proxy session runs it on an explicit, per-instance human authorization (CLAUDE.md #1906).

  It is **not** an ARCH-ESC. It is a human action (H-2), and the rule above binds.

### AD-10: The consumer path. Provision at install, dual-read at runtime, tripwire forever.

1. **At install.** `hos_install.sh` ships `contract/labels/` (S1's `_REGISTRY_KINDS` row). Then it runs
   `provision --apply` against the consumer repo *before* opening the upgrade PR (R1). It also puts
   `check` output and the consumer's open-`needs-ai` count (`migrate --dry-run` summary) into the upgrade
   PR body, with the migration steps. The installer mutating consumer GitHub state is a product-boundary
   item: **ARCH-ESC-1**. S6b waits for it.
   > **Erratum (2026-10-20, S1 TD review, TD-1520-S1 §18.3).** S1's `_REGISTRY_KINDS` row does **not**
   > ship `contract/labels/`. It mirrors pack layers only. S6b ships every file consumers need:
   > `contract/labels/core.yaml` (with its manifest row and `.gitattributes` line), `label_registry.py`,
   > `labels_cli.py`, `provision_labels.sh`, the package `__init__.py` markers, and the shared engine
   > modules, unless #1643 W7 has already shipped them. S6b does not wait for W7.
2. **At merge.** The consumer's code dual-reads. Un-migrated `needs-ai` issues stay selectable and
   authorized, so the queue never goes silently empty. If provisioning was skipped or failed, the
   preflight (AD-7) says so on every cycle. A `labels=needs-worker` query on a missing label returns
   either an empty list (the union still includes legacy) or an error (exit 2, which is loud). Neither is
   silent.
3. **Later.** The consumer operator runs `migrate` as a bot (AD-9).
4. **A consumer that skips the window release** gets the post-close tripwire (AD-6). With an empty
   `needs-worker` set, that is exit 3 and an `INCOMPLETE` log line, never "no work".
5. **Release notes.** The window-open release's notes must carry the consumer steps (provision, verify,
   migrate, and the human-facing switch from `needs-ai` to `needs-worker` for the authorizing act).

### AD-11: The window closes on measured criteria, all of which must hold.

- **WC-1.** `migrate --verify` against this repo reports **0** open issues and **0** open PRs carrying
  `needs-ai`.
- **WC-2.** **Zero** `legacy-label-present` audit events in this repo for **7 consecutive days** of
  cycles. That covers human muscle memory.
- **WC-3.** The window-open release (H-3) has been tagged, and S8 ships in a **strictly later** release.
- **WC-4.** The known-consumer condition set by ARCH-ESC-2.

S8 is filed at window open, in the next milestone, so the window can never be open-ended. S8's PR body
must carry WC-1 to WC-4 evidence. Its surfaces are protected, so the CODEOWNERS gate applies.

**After the window:**
- The legacy list read goes, and so do the PR-routing legacy names in `bin/hos-cron`.
- The tripwire and the authorization alias stay.
- The registry entry for `needs-ai` moves to `retired`.

### AD-12: Coupling with #1644 AD-C17 (one window, one script, one test).

- #1520 S1 delivers **the** provisioning tool and **the** conformance test. #1644 T3.1 delivers
  `contract/stages/core.yaml`, the `stage` family provider, the `hos:round-reset` entry and their
  `docs/LABELS.md` rows. **No second script and no second test.**
- **Release rule (ESC-5(a), binding).**
  - The **window-open release** (H-3) is the first tag carrying S3a/S3b/S4. It must also carry T3.1, so
    consumers absorb `stage:*`, `needs-worker` and `needs-overseer` in one upgrade.
  - Merges to `main` are not constrained by this rule. This repo runs `main`.
  - If T3.1 is not on `main` at the cut, the cut waits. This is AD-C17's stated remedy, applied at
    release time. With VF-8, W5's loader exists, so T3.1's ADR-1643 dependency appears satisfied.
- **AD-C17's migration-safety statement holds unchanged.** An un-migrated issue has no stage label and
  starts at `plan`.

---

## 3. Slice plan

Every slice has ≤15 files and ≤10 commits. "Prot." means it touches `scripts/framework/protected_surfaces.txt`
entries, so it passes the CODEOWNERS human gate. Each slice shrinks `[pending]` (P4) and updates
`docs/LABELS.md` rows and citations for what it changes.

| # | Slice | Files (complete list) | Depends on | Prot. | Human input needed to *code* |
|---|---|---|---|---|---|
| **S1** | **Registry kind, provisioning tool (`check`/`provision`), conformance test, `KNOWN_LABELS` fix. No behavior change. THE FIRST SLICE.** | `contract/labels/core.yaml` (new); `scripts/automation/lib/label_registry.py` (new); `scripts/automation/lib/dimension_registry.py` (one `KINDS` row); `bootstrap/hos_install.sh` (one `_REGISTRY_KINDS` row only); `scripts/framework/labels_cli.py` (new); `bootstrap/provision_labels.sh` (new); `scripts/framework/label_literal_allowlist.txt` (new); `tests/framework/test_labels_cli.py` (new); `tests/framework/test_label_conformance.py` (new); `tests/framework/test_install_registry_data.py` (only if T5.44 needs a fixture update); `docs/LABELS.md`; `scripts/framework/check_agents_static.sh`; `tests/oversight/test_agents_static_logic.py`; `SCRIPTS-INDEX.md` (regenerated) | nothing | yes | **None.** `needs-worker`/`needs-overseer` are `planned`, and `needs-ai` is `active`. **Erratum (2026-10-20, S1 TD review):** the file list also needs `tests/automation/test_dimension_registry.py` (T5.43 pins `registered_schemas()`), and `test_install_registry_data.py` is not needed. The binding list is `TECHNICAL-DESIGN-1520-S1-label-registry.md` §2 (14 files). |
| H-1 | **Human:** provision this repo | Run `bootstrap/provision_labels.sh --apply`, then post the `check` output on #1520 | S1 merged | — | Human act. It gates the **merge** of S2a and later slices, not their coding. |
| **S2a** | Issue-side dual-read and the authorization alias | `scripts/framework/pending_actor_labels.py` (new); `scripts/framework/requester_trust.py`; `scripts/framework/select_work_candidates.py`; `scripts/automation/lib/probe.py`; `tests/framework/test_requester_trust.py`; `tests/framework/test_select_work_candidates.py`; `tests/framework/test_select_work_candidates_ghshim.py`; `tests/framework/test_select_work_candidates_native.py`; `tests/framework/test_selection_call_sites.py`; `tests/automation/test_probe.py`; `contract/labels/core.yaml` (`needs-worker` becomes `active` as a reader); `scripts/framework/label_literal_allowlist.txt`; `docs/LABELS.md` | S1; H-1 before merge | yes | None. Trust-gate change: **security-reviewer is mandatory**, plus cross-vendor second review at tier. T-A1 to T-A5 and T-A7. |
| **S2b** | PR-side dual-read and legacy measurement in `bin/hos-cron` | `bin/hos-cron` (`:1203-1224` mapping per AD-4; context and directive text at `:2076-2078` and `:2094`; logging and audit of `legacy_label_records`); `tests/automation/test_hos_cron.py`; `scripts/framework/label_literal_allowlist.txt`; `docs/LABELS.md`. If T3.0b has landed: `scripts/framework/classify_worker_prs.py` and its test, instead of the bash block. | S2a | yes | None |
| **S3a** | Writer switch: launcher, workflow, bootstrap | `bin/hos-cron` (issue filings at `:1085,1823,1898,2194`; `check` preflight per AD-7); `.github/workflows/label-swap.yml` (`/handoff` removes both names in separate calls, and the `/approve` text names `needs-worker`; slash-command names unchanged); `bootstrap/create_issue.sh` (usage comment); `bootstrap/escalate_to_human.sh` (comment); `tests/automation/test_hos_cron.py`; `tests/automation/test_create_issue.py`; `tests/automation/test_escalate_to_human.py`; `contract/labels/core.yaml` (`needs-ai` becomes `legacy-read`); `scripts/framework/label_literal_allowlist.txt`; `docs/LABELS.md` | S2a, S2b, H-1 | yes | None |
| **S3b** | Writer switch: library writers and the `needs-overseer` writer | `scripts/automation/lib/merge_authority.py` (`:634`; `record_pr_bounce` add/remove per AD-4); `scripts/automation/lib/self_review_source.py` (also confirm or fix VF-6's suspected `--field` array defect); `bootstrap/submit_pr.sh` (add `needs-overseer` after the PR is created, best-effort and logged); `tests/automation/test_phase_b.py`; `tests/automation/test_phase_c.py`; `tests/automation/test_submit_pr.py`; `contract/labels/core.yaml` (`needs-overseer` becomes `active`); `scripts/framework/label_literal_allowlist.txt`; `docs/LABELS.md` | S2a, S2b, H-1 | yes | None |
| **S4** | Agent definitions and runtime prompts | `.claude/agents/worker.md` (`:156` → `needs-overseer`; the how-to-authorize block at `:174-177`; `:180`, `:237`, `:270`, `:326-332`, `:424`); `.claude/agents/overseer.md` (`:161` title-based dedup per VF-10; `:163`; `:334`, `:338`, `:756`; the canonical-labels table at `:799-812`, aligned to `docs/LABELS.md` with the `needs_ai` adaptation advice removed); `.claude/agents/pm-agent.md`; `bootstrap/worker-cron-prompt.md` (Step 0 routing, Step 1 swap, Step 2 heading); `bootstrap/overseer-cron-prompt.md` (`:38` dedup); `.claude/commands/hos-triage.md`; phase-1 validation stamp(s); `scripts/framework/label_literal_allowlist.txt`; `docs/LABELS.md` | S1 (`KNOWN_LABELS`), S2a, S2b | yes (`.claude/agents/**`, `bootstrap/**`) | None |
| **S5** | Live docs and the DECISIONS entry | `CLAUDE.md`; `contract/OVERSIGHT-CONTRACT.md` (`:440`, `:467`; event rows for `legacy-label-present`, `labels-unprovisioned`, `labels-provisioned`, `labels-migrated`); `METHODOLOGY.md`; `docs/AGENTS.md`; `docs/OVERSIGHT-RUNBOOK.md`; `docs/CRON-SETUP.md`; `docs/CROSS-REPO-CONDUCT.md`; `docs/COST-MANAGEMENT.md`; `docs/LABELS.md` ("The `needs-ai` authorizing act" becomes the `needs-worker` act, with a legacy note); `DECISIONS.md` (one new entry appended at the bottom); `scripts/framework/label_literal_allowlist.txt` | S3a, S3b, S4 | yes | None |
| **S6a** | The migration tool | `scripts/framework/labels_cli.py` (`migrate`: dry-run default, `--apply`, `--verify`, partition check, bot-only identity); `bootstrap/migrate_labels.sh` (new); `tests/framework/test_labels_cli_migrate.py` (new, including T-A6); `scripts/framework/label_literal_allowlist.txt` (`[legacy-readers]`); `docs/LABELS.md`; `SCRIPTS-INDEX.md` | S1, S2a | yes | None |
| **S6b** | Consumer upgrade path | `bootstrap/hos_install.sh` (provision at install, `check` and the legacy count in the upgrade PR body); `tests/framework/test_install_labels.py` (new); `docs/LABELS.md`; release-notes text for H-3 | S6a; **ARCH-ESC-1** | yes | **ARCH-ESC-1** |
| H-2 | **Human:** relabel this repo | `migrate --dry-run` (the worker may run it and post the output), then a human runs `migrate --apply --app human` | S3a, S3b, S4, S6a | — | Human act (AD-9) |
| H-3 | **Human:** window-open release cut | The release carries S1 to S6b **and** #1644 T3.1 (AD-12) | all of the above; T3.1 | — | Existing NG3b release gate |
| **S8** | Close the window | `scripts/framework/select_work_candidates.py` (legacy list becomes the tripwire, plus the exit-3 rule); `scripts/automation/lib/probe.py`; `scripts/framework/pending_actor_labels.py`; `bin/hos-cron` (legacy PR names removed); `contract/labels/core.yaml` (`needs-ai` becomes `retired`); their tests; `scripts/framework/label_literal_allowlist.txt` (`[pending]` empty); `docs/LABELS.md` | WC-1 to WC-4 (AD-11); **ARCH-ESC-2** | yes | **ARCH-ESC-2** |

**Why S1 comes first.** It needs nothing:
- It changes no control flow, mutates no live GitHub state, and needs no ruling.
- It turns both of `docs/LABELS.md`'s "Known gaps" into code.
- It gives every later slice a mechanical progress check (P4).
- It gives #1644 T3.1 its extension point (AD-7 families).

If everything after S1 slips, S1 is still worth having.

**Risk tiers (for the risk-assessor, not a ceiling):**
- S2a is security-relevant: it is a trust-gate predicate.
- S2b and S3a change the launcher's routing.
- S1, S5 and S6a are MEDIUM-class tooling and docs.

---

## 4. What #1520's open questions resolve to

The prior draft left three questions open.

1. **Where does provisioning live?** In `bootstrap/provision_labels.sh` → `scripts/framework/labels_cli.py`,
   reading `contract/labels/core.yaml` (AD-7). The installer invokes it subject to ARCH-ESC-1. Humans run
   it in this repo (H-1).
2. **Is the dual-read cost indefinite?** No. The full legacy list read ends at S8, under AD-11's measured
   criteria. What remains permanently is a one-request tripwire, ≤1% of the budget, and the cost-free
   authorization alias.
3. **GitHub create-on-apply?** It was not measured (VF-12), and the design does not depend on it:
   - R1 provisions before any write.
   - `check` detects missing labels.
   - `present-unprovisioned` detects auto-created ones.
   - H-1's run is the first observation.

---

## 5. Cross-ADR effects and the affected sign-offs (startup-gap recovery)

Should this have been settled in an earlier review? Partly. DECISIONS.md 2026-09-06 deliberately deferred
the mechanics. No design or code has been **approved against a superseded version of this ADR**, so no
sign-off is orphaned outright. Three approved or pending artifacts are affected:

- **ADR-1644, T3.1 row.**
  - "Provisioning script, conformance test" now means: *extend #1520's tool and test with the `stage`
    family and rows* (AD-7, AD-12).
  - VF-C10 is stale (VF-8).
  - T3.1 has no TD yet, so no sign-off is affected. Its `technical-design` must read this ADR.
- **TD-1644-T3.0b** (APPROVED_WITH_EDITS, coder blocked on ARCH-ESC-1R). `BOUNCE_LABEL` becomes the `W`
  set (AD-4). **Delta re-check by the architect** when either S2b or T3.0b lands second. The approval
  stands otherwise. The mapping preserves behavior.
- **TD-1604 §1.1** (unbuilt). The `hos_labels.sh` constant file must not introduce a second definition of
  pending-actor names. Its `HOS_LABEL_AI` row is replaced by `pending_actor_labels.py`. Its new labels
  (`in-progress`, `timeout-stuck`, `blocked`) must be registry entries, and AD-8 P1 enforces that.
  **TD-1604 needs revision before it is coded.** Nothing is built, so nothing is orphaned.
- **TD-1540 S2** (shipped). S2a modifies the shipped gate. AD-4 (rename-survivability) and FR26 are
  preserved and strengthened. The full review chain applies to S2a as new code, and security-reviewer
  is mandatory.

---

## 6. Escalations (human decisions only)

### ARCH-ESC-1: May `hos_install.sh` create labels in a consumer's GitHub repo at install time? (Blocks S6b only.)

This is a product-boundary item. It is a new mutation of consumer-repo state performed by the installer.
It is visible to consumer users, and it adds a failure path to the installer.

- **(a)** The installer runs `provision --apply` by default before opening the upgrade PR. It is additive
  only: it never modifies or deletes. `--no-labels` opts out. A failure gives a loud warning and adds a
  checklist item to the PR body. The PR body also reports the open-`needs-ai` count. The installer
  **never refuses** an upgrade over legacy labels, because the runtime tripwire is the safety.
- **(b)** The installer runs `check` only, and prints the exact `provision` command for the operator.
- **(c)** No installer involvement. Release notes only.

**Recommendation: (a).** R1 needs the labels to exist when the upgrade PR merges. The installer already
holds gh auth to the consumer repo and already writes to it (`gh pr create`, the `needs-human` label at
`:2550`). Labels created before the merge are inert to the consumer's old code. Option (b) re-creates the
"hand-run setup step" gap `docs/LABELS.md` complains about. Option (c) relies on reading.

### ARCH-ESC-2: What must be true of known consumers before the window closes? (Blocks S8 only.)

HOS cannot observe consumer repos' label state in the normal flow. Only the operator knows whether `cps`
has run `migrate`.

- **(a)** S8's PR must carry a human attestation, per known consumer (today: `cps`), of a `migrate --verify`
  result of 0. Or it must carry an explicit human waiver for that consumer.
- **(b)** S8 closes on WC-1 to WC-3 alone. Consumers rely on the tripwire, which fails loud (exit 3 or a
  WARN), not silent.

**Recommendation: (a).** Option (b) is safe against a *silent* empty queue, which is the #1349 concern.
But it turns a consumer that has not migrated into a consumer whose worker stops with `INCOMPLETE` until
someone migrates. That is an outage the human should choose knowingly, not inherit from a release.

**Human actions (not escalations).** H-1 (provision this repo), H-2 (`migrate --apply`, per AD-9) and H-3
(the window-open release cut, under the existing NG3b gate).

---

## 7. Self-flag

**RISK:** MEDIUM overall. It is HIGH for S2a, which changes the authorization predicate of the
work-selection trust gate, and for H-2, which is a bulk mutation of live work state.

**CONFIDENCE:**
- **HIGH** on AD-1 to AD-6 and AD-9. Every load-bearing claim is cited against `c0462c1a6`.
- **MEDIUM** on AD-8's pattern list, which is heuristic by nature. P6 is the backstop, and
  `technical-design` fixes the exact patterns.
- **LOW** on VF-12 (create-on-apply) and on VF-6's suspected `--field` defect. Both are unmeasured, and
  nothing depends on them.

**BLAST RADIUS:**
- work selection in every worker cycle, in this repo and in consumers;
- PR routing in `bin/hos-cron`;
- the authorization predicate shared by `select_work_candidates.py` and `probe.py`;
- `label-swap.yml`'s human slash-command contract (the command names are unchanged; the label names
  change);
- the installer;
- every consumer's GitHub label set;
- five agent and prompt files;
- nine live docs;
- the #1644 T3.1 and T3.0b and the #1604 designs.
