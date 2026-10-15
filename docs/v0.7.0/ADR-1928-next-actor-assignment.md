# ADR-1928: Summon the expected next actor. One read-mostly reconcile pass per worker cycle, in a protected and shipped Python module, that assigns only the human, never touches a `release-request` assignee or any label, verifies every write by read-back, and posts marker-deduplicated reminders, a change-driven digest and persistent-condition issues

**Status:** ACCEPTED FOR DESIGN. AD-1 to AD-11 bind `technical-design`. Items marked **PROVISIONAL (ESC-n / ARCH-ESC-n)** are drafted on the stated default, and each names what changes under the alternative. REQ-H1 (NG3b non-collision) is not open to any ESC answer or agent-side waiver.
**Date:** 2026-10-15
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #1928 · **Milestone:** v0.7.0 · **Risk tier: HIGH.** Every slice lands on protected surface: `scripts/framework/**` (`protected_surfaces.txt:28`), `bin/**` (`:26`), `bootstrap/**` (`:27`) and `.claude/agents/**` (`:16`). The human gate therefore applies whatever tier is computed.
**Inputs:** `docs/v0.7.0/REQUIREMENTS-1928-next-actor-assignment.md` (VF-1 to VF-10, REQ-N1 to REQ-I3, ESC-1 to ESC-8). Also `ADR-1934-proxy-decision-risk-tiers.md` (AD-2, AD-9, §4 "#1928 interaction" `:151`), `bootstrap/escalate_to_human.sh`, `bootstrap/edit_issue.sh`, `bin/hos-cron`, `scripts/framework/select_work_candidates.py`, `scripts/framework/requester_trust.py`, `scripts/automation/lib/merge_config.py`, `scripts/oversight/codeowners.py:284`, `scripts/oversight/lib/audit_log.py`, `scripts/automation/lib/cycle_log.py`, `.claude/agents/worker.md:160-177,520-528,680-695,750-800`, `.claude/agents/overseer.md:466-468`, `docs/LABELS.md`, `research/findings/api-field-shape-verification.md`, `scripts/framework/framework_consumer_files.txt`.
**Consumers:** `technical-design` → `coder` → review chain. `security-reviewer` is mandatory on S1 and S2, because they add a writer to a field NG3b treats as a security anchor. `reliability-reviewer` is mandatory on S2 and S6, because they add a GitHub-dependent step to every cron cycle.
**Explicitly does NOT re-litigate:** NG3b R1 to R5, `BOT_ACCOUNTS`, the human-approval gate, ARCH-ESC-6 of ADR-1644, #1934's tiering (AD-1 to AD-9), the #1657 reviewer-request trigger set, or #2101's replacement of the authorization file.

---

## 0. Verification findings (working tree at `0f93f3973`)

### 0.1 Confirming pm-agent

- **VF-1 CONFIRMED.** `worker.md:520-521` ("GitHub Apps cannot be assigned to issues or PRs on this repo — confirmed by direct API testing (#1347)") and `:547-548`. All three App logins are in `BOT_ACCOUNTS` (`machine-accounts.env:29-38`). `HUMAN_REVIEWER="ScottThurlow"` (`:56`) is the only assignable role.
- **VF-2 CONFIRMED, with one sharpening.** `worker.md:524-528` (only permitted write is the R4 step 0 reset), `:685-689` (reset via `edit_issue.sh --set-assignee none`), `:760` (exactly one assignee), `:764-772` (latest `assigned` event must be a self-assignment), `:788` (CODEOWNER, not in `BOT_ACCOUNTS`), `:790` (`T_E > T_comment`). Sharpening: R4 step 0 always runs **immediately before** the request comment (`:685-689`), and R5.9 requires the self-assignment to post-date that comment. A bot assignment that lands *before* R4 step 0 is therefore cleared by step 0. The dangerous window is a bot assignment landing **after** the request comment and before the human self-assigns. That window exists only if a writer ignores a `release-request` label that is already visible. AD-4's live re-read closes it except for a label applied in the same instant as the write, and AD-4's post-write check undoes even that.
- **VF-3 CONFIRMED.** `docs/LABELS.md:30` lists the writers. `bin/hos-cron:2179-2197` files breaker issues with `gh issue create --label "needs-human,needs-ai"`. Only `escalate_to_human.sh` carries a reason and a record (`:5-8`, `:21-25`).
- **VF-4 CONFIRMED.** `edit_issue.sh:25-29` (add-only `POST /assignees`), `:187-191` (`--set-assignee` folds `assignees` into a PATCH, which **replaces** the list), and `:215-219`. `:222-224` prints the result but does not check that the requested login is present.
- **VF-5, VF-7, VF-9 CONFIRMED.** `overseer.md:466-468`; `bin/hos-cron:2354`; `worker.md:171-177`.
- **VF-6 CONFIRMED.** No push sender exists in `bin/`, `bootstrap/` or `scripts/`.
- **VF-8 CONFIRMED.** `bin/hos-cron:390` writes `cycle-tmp-root-fallback` and nothing else. The breaker's dedup (`:2186-2206`) and auto-close (`:2283-2300`) are inline shell, fail-closed, and keyed on a title prefix only.

### 0.2 Architect findings (these change the design)

**AF-1 (HIGH): "idle" is not one code point, and the common idle path never reaches `outcome: idle`.** `bin/hos-cron:2354` is reached only after Claude has run and exited 0. The cheap idle exits come earlier and `exit 0` without reaching it: `cycle-skip reason=no_actionable_work` (`:1310-1312`, worker), `no_open_prs` (`:1343-1345`, overseer) and `no_actionable_prs` (`:1364-1366`). A cycle in which every candidate is gated, which is the #1776 case, logs `ALL WORK CANDIDATES GATED` (`:1292-1294`) and is either a cheap skip or a model launch that ends idle. A digest hooked only at `:2354` would miss most of the nine days the 2026-10-15 report describes. AD-6 evaluates the digest every cycle on REQ-D2's change/interval rule, and drops the coupling to cycle outcome (ARCH-ESC-1).

**AF-2 (HIGH): a milestone-less HOS-filed issue disables the #1395 cheap skip for every later worker cycle.** The actionable-work gate counts **any** open milestone-less issue as work (`:1141-1146`, "unfiltered by label"), so `:1307` can never take the skip while one exists. A standing digest issue (REQ-D3) or a REQ-I1 issue filed without a milestone would make every 15-minute worker fire pay for git sync, the baseline test run and a model session. The timeout-breaker issue (`:2193`) already has this defect (routed as N-1). AD-6 and AD-7 file into the target milestone.

**AF-3 (HIGH): the "HOS-made" test must read `assigner`, never `actor`.** On an `assigned` event, `actor` is the **assignee** and `assigner` is the performer (`research/findings/api-field-shape-verification.md:16-17`, `:34`, #348). An implementation that reads `actor.login` would classify every bot assignment of the human as human-made and never unassign it. It would also classify the human's own self-assignment by its assignee. AD-5 fixes this, and the null case leaves the assignment in place.

**AF-4 (HIGH): the brief's preferred locus `scripts/automation/lib/` is unprotected and not shipped.** `protected_surfaces.txt` covers `scripts/framework/**` and `scripts/oversight/gates/**`, not `scripts/automation/**`. `framework_consumer_files.txt` ships `bin/hos-cron` (`:22`) and the selector (`:98`), but nothing under `scripts/automation/`. The selector made the same choice for the same reason: it does not import `scripts/automation/lib/github.py` because that "sits on an unprotected surface" (`select_work_candidates.py:229-237`). A module whose job is to keep a bot off the NG3b anchor must not be editable without the human gate. If it lived in `scripts/automation/lib/`, an overseer-only PR could weaken the REQ-H1 guard, and consumers' `hos-cron` would call a module that is not installed. AD-1 places it in `scripts/framework/`. It is still Python and still on the v0.7.4 shell→Python direction.

**AF-5 (MEDIUM): a per-writer hook in `escalate_to_human.sh` buys about one cron interval and costs a merge collision.** Without the hook, a reconcile pass on the next worker fire assigns the human anyway, about 15 minutes later. With it, the script gains a second post-label write path, so its exit-code contract (`:31-42`) has a new partial-failure mode under REQ-H3. It would also collide with #1934 S2 on the same file (`ADR-1934:121`). AD-3 does not add the hook. With no hook, assignment (S2) no longer depends on #1934 S2. Only the action block (S3) does.

**AF-6 (MEDIUM): two writers would stop the reconciler before it ever ran on their issue.** The timeout breaker suspends the project (`:2179-2183`), and `hos-suspend` exits before auth (`:270-291`). Its own `needs-human` issue would therefore never be assigned by a cycle-time pass. AD-3 gives this one writer a direct call to the primitive.

**AF-7 (MEDIUM): conditions that stop a cycle before auth cannot be escalated from inside the cycle.** That covers the usage pause (`:484`), preflight auth failures (`:950-1024`), the halt check (`:1038-1055`) and suspension. The attention pass needs a token, so it runs after these. This is a stated residual (R-2), not something AD-7 can fix.

**AF-8 (LOW): hos-cron's per-project knobs live in `projects.conf`, not `config.sh`.** Examples are `<project>_max_seconds` (`:32`), `_worktree_hygiene` (`:58`) and `_baseline_on_red` (`:99`). ESC-6's cadences therefore become `projects.conf` keys passed to the module as arguments.

**Reuse search (CLAUDE.md item 1).** I searched `scripts/`, `bootstrap/`, `bin/` and `scripts/automation/lib/` for an assignee writer with read-back, an issue-events reader, a GitHub-visible dedup marker helper, and a persistent-condition primitive.
- Found: `edit_issue.sh --assignee/--set-assignee`. It has no `release-request` guard, no read-back assertion and no `DELETE /assignees`. It cannot gain a `release-request` refusal, because R4 step 0 legitimately calls it on exactly those issues (`worker.md:687`).
- Found: `escalate_to_human.sh`'s marker and own-comment match (`:213-243`). This is the pattern AD-6 copies.
- Found: `requester_trust.load_bot_accounts` (`requester_trust.py:301`) and `merge_config.resolve_config(...).human_reviewer` (`merge_config.py:64-105`).
- Found: `audit_log.write_event` (`scripts/oversight/lib/audit_log.py:126`), loaded by path as in `cycle_log.py`.
- Found: `scripts/automation/lib/breakers.py`. It is the T13 customer-probe path and uses local `.ai-local` state only, so it is not reusable for GitHub-visible dedup.
- Found nothing that verifies an assignment, removes a single assignee, or derives a clock from label events.

---

## 1. Organizing principle

**The label is the block. The assignment is only a notification. The pass may write notifications but never blocks.** The mechanism reads labels and never writes the `needs-human` label. It writes exactly one field kind on other people's objects (an assignee, add or remove one login), and only after a live re-read. It writes comments only on its own standing issue, on its own condition issues, and as marker-carrying reminders. Nothing it writes is read by any gate (REQ-H4). Every write it makes is checked by reading it back. A failed write is reported loudly and nothing is retried in a tight loop, because the next cycle converges.

---

## 2. Decisions

### AD-1: Code locus: two stdlib-plus-`gh` modules in `scripts/framework/`, both shipped. hos-cron keeps only call glue. (BINDING; AF-4, D41.)

- **`scripts/framework/next_actor.py`.** It holds the pure REQ-N1 function and the assign/unassign primitive.
  - CLI: `query --number N`, which prints the actor as JSON (read-only, the REQ-N2 query surface).
  - CLI: `assign --number N` and `unassign --number N`.
  - It never writes a label, a body or any state.
- **`scripts/framework/attention_pass.py`.** It is the per-cycle orchestrator: reconcile (AD-3), reminders (AD-5b), digest (AD-6) and conditions (AD-7).
  - It imports `next_actor` for every assignee write. **No other code in the repo writes an assignee except `edit_issue.sh`'s two existing flags.**
- **GitHub access.** Both modules call `gh api` through `subprocess`, on the cycle's already-minted token, following `select_work_candidates.py:229-253`. Write bodies are sent as JSON on stdin (`--input -`, the #1155 rule). Neither module imports `scripts/automation/lib/github.py`.
- **Audit.** Events go through `scripts/oversight/lib/audit_log.write_event`, loaded by path (the `cycle_log.py` idiom). The shape follows REQ-N7 and `escalate_to_human.sh:172-179`.
- **Configuration.** `requester_trust.load_bot_accounts` for bots and the `HUMAN_REVIEWER` line of `machine-accounts.env`. `technical-design` decides whether to reuse `merge_config.resolve_config`'s parser or the selector's. It must not write a third parser.
- **Shipping (ESC-8 default).** Both files are added to `framework_consumer_files.txt` in the slice that creates them. `escalate_to_human.sh` stays HOS-only (ADR-1934 AF-1), so S3 does not ship.
- **One invocation site per entry point.**
  - The pass is called from exactly one place: AD-2's hook in `bin/hos-cron`.
  - `next_actor.py assign` is called from the pass and from the breaker trip path only (AD-3, AF-6).
  - `query` has no production caller. It exists for agents and humans.

### AD-2: The pass runs once per cycle, after the halt check and before any idle skip, under a timeout, and never fails the cycle. (BINDING on placement and non-fatality; AF-1, AF-7.)

- **Placement.** Run it in `bin/hos-cron` immediately after the hos-halt check (`:1051-1056`) and before the agent-availability check (`:1058`). At that point the token and identity guard have passed (`:955-975`), `_REPO_SLUG` is set (`:943`), the kill switch has been honoured, and none of the cheap-skip exits (`:1310`, `:1343`, `:1364`) has run yet.
- **Invocation.** `timeout --kill-after=5 <N> python3 -m scripts.framework.attention_pass --repo "$_REPO_SLUG" --role "$ROLE" --project "$PROJECT" [--milestone N] [--observed <key>=<detail> …] [cadence flags]`, run from `REPO_ROOT`. The cadence flags come from `projects.conf` (AF-8).
  - **Default `N` = 90 s.**
  - Any non-zero exit (including 124) is logged as `WARN attention pass rc=<n>` and written as `cycle-attention-pass-failed`.
  - The cycle always continues.
- **Role split.** Under `--role overseer` only AD-7 runs, for the overseer's own observed conditions. Under `--role worker` everything runs. Worker-only ownership plus hos-cron's per-role overlap lock (`:320-335`) means one human-facing writer at a time per project. That satisfies REQ-D4 and REQ-R2 by construction, not by a race-prone two-role protocol. Suspension and hos-halt stop both roles together, so overseer participation would add no coverage.
- **Budget.** The pass stops issuing calls when either limit is reached: **200 API calls**, or the time left before the timeout drops below a safety margin. It writes `attention-pass-degraded` naming the items it did not process. Items are processed oldest `labeled` first, so starvation always favours the longest wait. `technical-design` measures the call count on the live repo and records it in the S2 PR.
- **Slow sub-steps.** Reminders and digest do the per-item events and comments reads. They are evaluated at most once per **60 min** per role-clone, using a local stamp under `$_HOS_DIR/attention/`. The stamp can only *skip* evaluation. It can never cause a write, so correctness stays GitHub-derived (REQ-R2). Reconcile runs every cycle.

### AD-3: Coverage is convergent reconcile, plus one direct call where the writer stops the reconciler. No hook in `escalate_to_human.sh`. (BINDING; REQ-N4, AF-5, AF-6.)

- **Desired state.** Every open issue or PR carrying `needs-human`, other than `release-request` issues and AD-6's standing issue, has `L` among its assignees, where `L` is the resolved human (AD-4).
- **Reads.** Two list queries, each paginated to completion or marked bound-reached, never silently truncated:
  - `GET /issues?state=open&labels=needs-human` (returns issues and PRs);
  - `GET /issues?state=open&assignee=L`.
- **Writes.** Assign wherever the desired state is unmet. Unassign `L` where `needs-human` is absent **and** AD-5 classifies the current assignment as HOS-made. Running the pass a second time over unchanged state issues no write (REQ-N4 AC).
- **Breaker path.** After a successful filing at `:2193`, the timeout-breaker trip calls `next_actor.py assign --number <filed>`. This is best-effort and never changes the breaker's own flow. It is the only per-writer call. Every other writer, including a human applying the label by hand, is covered by the next worker cycle.
- **Rejected options.**
  - **Per-writer hooks everywhere (8+ sites, including `label-swap.yml` and humans):** they cannot cover the hand-applied case, so a reconcile pass is needed anyway.
  - **Hook in `escalate_to_human.sh` in addition (AF-5):** about 15 minutes of latency gained, at the cost of a new partial-failure mode in a script with a fixed exit-code contract, plus a collision with #1934 S2.

### AD-4: The assign primitive. Resolved login, assignability pre-check, live `release-request` re-read, add-only endpoint, read-back, post-write NG3b check. (BINDING; REQ-N3, REQ-N5, REQ-H1, REQ-H3, ESC-2(i).)

`assign(N)`, in this order. Each step stops on failure and records its outcome.
1. **Resolve `L`** = `HUMAN_REVIEWER`, for issues **and** PRs.
   - Refuse with `next-actor-unresolved:<why>` if `L` is empty, is in `BOT_ACCOUNTS` (case-insensitive), or does not match a user-login pattern.
   - **Rejected for v1:** reusing `resolve_human_reviewer` (`codeowners.py:284`) for PRs. In HOS it returns the same login today. In a consumer with several human CODEOWNERS it would introduce a second resolution rule whose unassign semantics (which login was "ours"?) the reconcile would also have to track. #1936 must revisit both (FU-1).
2. **Assignability.** `GET /repos/{o}/{r}/assignees/{L}`: 204 means assignable, 404 means `next-actor-unresolved:not-assignable`, anything else means `assign-failed:precheck`. The result is cached per pass. This makes correctness independent of whether GitHub silently drops a non-assignable login (ESC-2(i)).
3. **Live re-read.** `GET /issues/{N}` immediately before the write.
   - Refuse with `next-actor-refused:release-request` if `release-request` is present.
   - Skip with `next-actor-skip:<why>` if the object is closed, `needs-human` is absent, or `L` is already assigned.
4. **Write.** `POST /issues/{N}/assignees` with `{"assignees":[L]}`. **PATCH with an `assignees` key is forbidden in both modules**, because it replaces the whole list, and an AST/grep test pins this.
5. **Read-back.** `GET /issues/{N}`. Success requires `L ∈ assignees`. Otherwise the outcome is `assign-unverified` (REQ-N5).
6. **Post-write NG3b check.** If that same read-back shows `release-request`, the pass immediately runs `DELETE /issues/{N}/assignees` for `L` only and records `ng3b-race-undone` (audited at WARN, listed in the digest).
   - Why this is safe: R4 step 0 always clears and re-anchors before the request comment (`worker.md:685-689`), and R5.9 requires the self-assignment to post-date that comment. A transient bot assignment that has been undone therefore cannot satisfy or block R5.

**`unassign(N)`** runs the same step 3 (refuse on `release-request`, on any code path, REQ-H1 AC). It then runs AD-5's classification, `DELETE /issues/{N}/assignees` with `{"assignees":[L]}` (that login only, never another assignee), and a read-back confirming `L ∉ assignees` (`unassign-unverified` otherwise).

**Exit contract (CLI).**
- 0: done, skipped or refused-by-design.
- 1: transient read failure.
- 2: usage error.
- 4: write failed or unverified.

The pass maps each item's result to an audit event and continues with the next item. Nothing in either module writes, removes or reorders a label (REQ-H3 holds by construction), and this is pinned by a test that asserts no `/labels` write endpoint appears in either module except AD-6/AD-7's creation of their own issues.

### AD-5: "HOS-made" means the latest `assigned` event for `L` has `assigner.login ∈ BOT_ACCOUNTS`. Anything else, including a null `assigner`, is left alone. (BINDING; REQ-N6, AF-3. PROVISIONAL on scope, ESC-3.)

- **Classification.** Read `/issues/{N}/events`, paginated, and take the most recent `event == "assigned"` whose `assignee.login == L`.
  - HOS-made iff `assigner.login` is non-null and in `BOT_ACCOUNTS`.
  - Never read `actor` for this decision. On these events `actor` is the assignee (AF-3).
  - A null or absent `assigner`, an events read failure or a bound-reached page all classify as **not HOS-made**. Leaving an assignment in place costs one stale notification. Removing a human's own act is the failure to avoid.
- **Residual (stated).** GitHub records no new `assigned` event when someone already assigned assigns themselves. A human who "claims" an item HOS already assigned to them therefore stays classified as HOS-made, and is unassigned when `needs-human` is removed. This is accepted under ESC-3's default.
- **AD-5b, reminder clock (REQ-R1, REQ-R4).** The clock is the most recent `labeled` event for `needs-human`, identified by its event `id` and `created_at`.
  - **Reminder `k` (k ≥ 1)** is due at `created_at + first + (k-1)·repeat`. Defaults: `first = 24 h`, `repeat = 72 h` (ESC-6).
  - **Marker.** Each reminder carries `<!-- hos-attention-reminder v=1 since=<event-id> k=<k> -->` as its last line.
  - **Dedup.** If a bot-authored comment with that exact marker exists, reminder `k` is not posted. Only the highest due `k` is ever posted, so a long outage produces one catch-up reminder, not a burst.
  - **Restart.** Re-labelling creates a new event id, so the clock restarts with no extra code.
  - **Where reminders go.** Reminders are issue comments only. PRs are digest-only (ESC-4 default), and `release-request` issues get none (REQ-H2).
  - **Content.** The reminder @mentions `L` and quotes the item's Action line verbatim (AD-8).

### AD-6: The digest is evaluated every worker cycle, posted on a change of the human-item set or once the interval has passed, rate-limited, on one standing issue found by marker and filed into the target milestone. (BINDING on mechanism; PROVISIONAL on trigger, ARCH-ESC-1, and on cadence, ARCH-ESC-2. REQ-D1 to REQ-D4, AF-1, AF-2.)

- **Item set.** Every open `needs-human` object from AD-3's read, `release-request` issues included, minus the standing issue itself. Each row carries:
  - the URL and the age;
  - the next actor;
  - the #1934 tier when an `hos-escalation v=2` marker carries one (otherwise `hard-tradeoff`, per ADR-1934 AD-1);
  - the quoted Action line, or `no action recorded`;
  - the assignment state: `assigned`, `not assigned: release-request`, `not assigned: <unresolved reason>` or `assign-unverified`.

  It also lists the open AD-7 conditions and any `ng3b-race-undone` or degraded-pass events since the last digest.
- **Fingerprint.** `sha256` over the sorted `(number, action-line-hash, assignment-state)` tuples. The last digest comment carries `<!-- hos-attention-digest v=1 fp=<16 hex> -->`.
- **Post when** the set is non-empty **and** one of these holds:
  - (a) the fingerprint differs from the last digest's **and** at least `min_gap` (default 60 min) has passed since that digest;
  - (b) `repeat` (default 24 h) has passed since that digest.

  N cycles over unchanged state produce one digest (REQ-D2 AC). "Last digest" is read from GitHub, so a clone reset never re-posts.
- **Trigger is decoupled from cycle outcome (AF-1).** The rule runs on every worker cycle, busy or idle. That is a superset of REQ-D1's "on idle", bounded by the same REQ-D2 rule (ARCH-ESC-1).
- **Standing issue.**
  - **Lookup.** One open issue authored by the worker App whose body carries `<!-- hos-attention-digest-home v=1 -->`, found by one list query.
  - **Fail-closed dedup** (the `:2186-2206` pattern). A query error means skip, never file. Two matches mean use the lowest number and record `digest-home-duplicate`.
  - **Created with:** the target milestone (AF-2), with milestone-less allowed only when hos-cron has none and recorded as `digest-home-milestoneless`; the informational label `hos-attention` (a new `docs/LABELS.md` row; no control-flow reader); no `needs-human` and no `needs-ai`, so the selector (`select_work_candidates.py:111`, which requires `needs-ai`) and Step 0 triage both ignore it; and `L` assigned through AD-4.
  - **Exclusion.** AD-3's reconcile excludes the standing issue by its marker. Otherwise "next actor = none" would unassign `L` from it.
  - **Content.** Each digest comment @mentions `L`.
- **Channel guarantee (ESC-2(ii)/(iii)).** The digest @mention is the first-notification channel, and it does not depend on assignment notifications. A new human item changes the fingerprint, so the human is @mentioned within one worker cycle plus at most `min_gap`. Whether GitHub notifies on an App-made assignment, or on a comment on an assigned issue, is then a bonus, not load-bearing.

### AD-7: Persistent conditions: a counter per role-clone, an issue per condition-and-role found by marker, auto-closed on recovery. First key: `cycle-tmp-root-fallback`. (BINDING; REQ-I1 to REQ-I3, PROVISIONAL ownership ESC-7.)

- **Observation.** hos-cron passes `--observed <key>=<detail>` for each condition it saw this cycle. The first, and only, registered key is `tmp-root-fallback`, set when `:390` fires (the reason is already sanitised at `:388`).
- **Registry.** Keys are a committed constant in `attention_pass.py`, each with its REQ-A1 action template. An unregistered key is refused, which prevents free-text conditions.
- **Counter.** `$_HOS_DIR/attention/conditions/<role>-<project>.json`, holding `{key: {seen_streak, clear_streak}}`. A cycle that reaches the pass increments one streak and zeroes the other. A cycle that exits before the pass changes neither. A conditions-only overseer run is the overseer's way to count.
- **File** when `seen_streak ≥ K` (default 3).
  - **Dedup.** An open bot-authored issue carrying `<!-- hos-attention-condition v=1 key=<key> role=<role> project=<project> -->` must not already exist, checked fail-closed as in AD-6.
  - **Created with:** `needs-human`, the target milestone (AF-2) and `hos-attention`.
  - **Body.** A REQ-A1 block whose Action is the exact command, `python3 bootstrap/lib/hos_tmp_root.py mark --repo <abs clone path> --role <role> --reviewed`, with Where = host plus absolute clone path, Who = the human in their own terminal, and Done when = the next cycle of that role no longer emits `cycle-tmp-root-fallback`. `technical-design` takes the exact command from `hos_tmp_root.py --help`, not from this ADR.
  - Assigned through AD-4, which happens naturally, because the issue carries `needs-human`.
- **Close** when `clear_streak ≥ K`: post a comment, then close the issue. This mirrors `:2283-2300`.
- **No new control.** The pass never halts, never suspends, and never writes `hos-halt` (REQ-I3).
- **Ownership (ESC-7 default).** #1928 owns the primitive and this registration. #2100 item 4 points here.

### AD-8: The action block is enforced at the filing script, parsed by the pass, and composes with #1934's item tiers. (BINDING on fields and refusal; grammar `technical-design`'s. REQ-A1 to REQ-A3.)

- **Required block.** `escalate_to_human.sh` refuses (exit 2, before any token mint, in the existing validation block `:84-118`) a body that lacks a block headed exactly `### Action needed` with four non-empty lines: `Action:`, `Where:`, `Who:` and `Done when:`.
- **Lint, not refusal.**
  - `Where:` should contain an absolute path or a URL. When the Action names a file or a command, it should also name a clone or role. This is a lint warning, not a refusal, because prose detection over-matches.
  - The fixture for the 2026-10-15 case (a file in a clone) must pass only with an absolute path.
- **Tiers.** Under #1934, the block may repeat per item (`### Action needed — <ITEM-ID>`). The digest then quotes the first item's Action line and shows the item count.
- **Prose.** The `worker.md:171-177` "How to authorize" block is replaced by the REQ-A1 block. Its tier list and stamp sentence, required by ADR-1934 AD-9, go inside `Action:`. `worker-cron-prompt.md:104` names the block.
- **Records the pass reads.** The pass reads Action lines **only** from bot-authored, unedited comments carrying an `hos-escalation` marker, the same trust rule as `escalate_to_human.sh:221-228`. A pasted block by anyone else is ignored (REQ-A3).

### AD-9: NG3b and authorization separation, stated and tested. (BINDING; REQ-H1, REQ-H2, REQ-H4.)

- **Forbidden strings.** No body the pass posts may contain `Authorization required:`, `Release candidate SHA:`, `hos-escalation`, `hos-recommendation` or `hos-proxy-decision`. The digest strips any of them from quoted Action lines and records `quoted-line-sanitised`.
- **`worker.md:520-528`.** The ban gains one sentence naming `next_actor.py` and `attention_pass.py` as bound by it. This edit is authored by the top-level session, not `coder` (CLAUDE.md, #1347).
- **`docs/LABELS.md`.** It gains: "An assignment made by HOS is a notification only. No gate reads assignee state except NG3b R5, which reads only self-assignments by a non-bot CODEOWNER."
- **Grep test (REQ-H4 AC).** No file under `scripts/framework/`, `scripts/automation/lib/`, `scripts/oversight/` or `.github/workflows/`, and not `bin/hos-cron`, reads `assignee`, except an explicit allowlist by name: `next_actor.py`, `attention_pass.py`, `bin/hos-cron`'s release-request context line (`:1157`, display only), `edit_issue.sh` and `query_issues.sh`.

### AD-10: Local kill switch and rollout. (BINDING on existence; PROVISIONAL default, ARCH-ESC-3.)

- **Kill switch.** The `projects.conf` key `<project>_attention_writes=0|1` (default 1). At 0, the pass computes and audits every intended write as `would-<action>` and writes nothing to GitHub. This is a local operational switch, not a gate and not `hos-halt`.
- **Report before merge.** The S2 PR body carries one live run with writes off against `thurlow-research/HumanOversightSystem`. The report lists every assign and unassign the first enforcing pass would make, including historical bot-made assignments on open, non-`needs-human` items that AD-5 would remove. The human reviews it at the protected-surface approval.

### AD-11: Boundaries. (BINDING.)

- **#1934 decides who.** `next_actor.next_actor()` accepts an optional tier and ignores it while Part B is held. It never returns `human-proxy` (REQ-N1).
- **Writes depend on one predicate only:** open, carries `needs-human`, and is not a `release-request` issue. The worker and overseer rows of REQ-N1 are informational. The PR bounce and needs-fix rows mirror `bin/hos-cron:1202-1232`, and an equivalence test pins them. Those rows affect no write, so a future drift between them and hos-cron is cosmetic (FU-2 makes hos-cron consume `next_actor`).
- **#2101** owns replacing the authorization file. AD-8 only makes the escalation name it.
- **#1428/#1657.** `pr_review.sh request-reviewer` and its trigger set are untouched. PR assignment (ESC-4) is additive.

---

## 3. Failure modes

| Failure | Behaviour | Direction |
|---|---|---|
| Pass crashes, times out or hits its budget | WARN plus `cycle-attention-pass-failed` or `attention-pass-degraded`. The cycle continues. Labels are untouched. | Label: unaffected (fail-open is impossible, because the pass never writes labels). |
| `L` unset, a bot or not assignable | No write. `next-actor-unresolved`. A digest row on every digest. | Loud |
| Assign POST fails or the read-back lacks `L` | `assign-failed` or `assign-unverified`, a digest row, retried next cycle by convergence | Loud |
| `release-request` present at re-read | Refused. Audited. A digest row. | Closed (no write) |
| `release-request` appears between write and read-back | Immediate single-login DELETE, `ng3b-race-undone` WARN, a digest row | Closed (undo) |
| Events read fails during unassign classification | Not HOS-made, so left in place | Toward keeping the human's state |
| Standing-issue or condition-issue query error | Skip. Never file. | Fail-closed dedup |
| Reminder marker read fails | Skip this item's reminder this cycle | Toward silence over a duplicate (the digest still covers it) |
| Token expires mid-pass | `gh` errors map to transient and convergence repairs them. A 90 s pass is well inside the token's 1 h life (memory: expired token fails gates open). | Loud |

**Residuals (stated, not hidden).**
- **R-1.** A label applied in the same instant as the write is handled by undo, not by prevention.
- **R-2 (AF-7).** Conditions that stop a cycle before auth (usage pause, suspension, auth failure) cannot be escalated from inside the cycle.
- **R-3 (AD-5).** A human's "claim" of an item HOS already assigned to them is indistinguishable from HOS's assignment.
- **R-4.** Latency from label to assignment is at most one worker cron interval. Latency to the first @mention is at most that plus `min_gap`.

---

## 4. Slices (each ≤15 files including tests; each independently mergeable)

| # | Slice | Files (indicative) | Protected? | Depends on | Merge hangs on |
|---|---|---|---|---|---|
| **S1** | `next_actor.py`: pure function, `query`/`assign`/`unassign`, AD-4, AD-5, audit. No caller. | `scripts/framework/next_actor.py` (new), `tests/framework/test_next_actor.py` (new), `tests/framework/test_next_actor_ng3b.py` (new), `framework_consumer_files.txt`, `prompts/…` mirror if required, `SCRIPTS-INDEX.md`: ≤6 | Yes | — | human approval only (inert) |
| **S2** | `attention_pass.py` reconcile (AD-3), the hos-cron hook (AD-2), the breaker call (AF-6), the kill switch (AD-10), the `hos-attention` label row, AD-9 prose and grep test. | `scripts/framework/attention_pass.py` (new), `bin/hos-cron`, `docs/LABELS.md`, `.claude/agents/worker.md` (`:520-528`, top-level session), `docs/CRON-SETUP.md` (`projects.conf` keys), `tests/framework/test_attention_reconcile.py` (new), `tests/framework/test_assignee_readers.py` (new), `tests/…/test_hos_cron_*` (hook placement), `framework_consumer_files.txt`, `SCRIPTS-INDEX.md`: ≤11 | Yes | S1 | **ESC-1**, ESC-3, ESC-4, ARCH-ESC-3; the AD-10 report in the PR body |
| **S3** | Action block (AD-8). | `bootstrap/escalate_to_human.sh`, `prompts/bootstrap/escalate_to_human.md`, `tests/automation/test_escalate_to_human.py`, `.claude/agents/worker.md` (`:171-177`, top-level session), `bootstrap/worker-cron-prompt.md`, `tests/framework/test_action_block_prose.py` (new): 6 | Yes | **#1934 S2** (same script; re-review of the #1644 T3.0a sign-off happens once, after both). Its `worker.md` edit composes with **#1934 S4** (same block, AD-9): whichever lands second rebases. | none beyond sequencing |
| **S4** | Reminders (AD-5b). | `attention_pass.py`, `tests/framework/test_attention_reminders.py` (new): 2-3 | Yes | S2. S3 is optional (degrades to "no action recorded"). | ESC-6 |
| **S5** | Digest and standing issue (AD-6). | `attention_pass.py`, `tests/framework/test_attention_digest.py` (new), `docs/LABELS.md` if not in S2: 2-3 | Yes | S2. S3 is optional. | ESC-5, ARCH-ESC-1, ARCH-ESC-2 |
| **S6** | Conditions primitive and tmp-root registration (AD-7). | `attention_pass.py`, `bin/hos-cron` (`--observed` from `:390`), `tests/framework/test_attention_conditions.py` (new): 3 | Yes | S2 | ESC-7 (coordinate #2100) |

**Order.** S1 → S2 → {S4, S5, S6 in any order}. S3 is independent of S1 and S2 and waits only on #1934 S2. **Codable before any human answer:** S1 (inert) and S3 (after #1934 S2). S2 may be built on the defaults, but it must not merge before ESC-1 is answered, because it binds the restated acceptance criterion. **Fastest relief:** S1, then S2, then S5 together cover both recorded incidents (summon plus @mention). S4 and S6 close the rest.

### Test obligations (all deterministic: `gh` is stubbed by a recording fake, and the clock is injected)

- **S1:**
  - the REQ-N1 table, every row, plus `release-request` and closed;
  - `L` unset, bot-listed and non-assignable (404) each give `next-actor-unresolved` with no write call;
  - stub drops the login gives `assign-unverified`;
  - **NG3b:** a `release-request` issue makes no assignee call on `assign`, `unassign` or a direct function call;
  - the label appears between the pre-read and the write: the post-write check issues exactly one DELETE for `L` and nothing else;
  - assigner = bot means HOS-made. assigner = human, assigner null, and `actor` = bot with assigner = human all mean not HOS-made (AF-3);
  - unassign never removes a second assignee;
  - AST test: no `PATCH` carrying `assignees`, and no `/labels` write.
- **S2:**
  - a label applied with no call to the mechanism gets assigned after one pass, and a second pass makes zero writes;
  - a removed label plus an HOS-made assignment gets unassigned; a human-made assignment is kept;
  - the standing issue is excluded;
  - a pass exception or timeout leaves the cycle exit and labels unchanged;
  - the hook sits after the halt check and before `:1310`, pinned by an anchor test (avoiding first-occurrence anchors: memory, "test anchors use first occurrence");
  - kill switch 0 means zero writes and a `would-*` audit;
  - the breaker trip calls `assign`;
  - the REQ-H4 grep test;
  - the existing NG3b and escalate tests pass unchanged.
- **S3:**
  - each missing or empty field gives exit 2 with no mint;
  - the clone-file fixture needs an absolute path;
  - a block with #1934 item IDs parses;
  - every existing T-ESC case passes after its fixture bodies gain a block;
  - the prose anchors.
- **S4:**
  - an item younger than `first` gets none;
  - an item older than `first` gets exactly one, over N cycles;
  - the next one comes only after `repeat`;
  - an outage gets one catch-up, not a burst;
  - re-labelling restarts the clock;
  - two sequential cycles in the same interval give one comment;
  - none on PRs and none on `release-request`;
  - the forbidden-string scan.
- **S5:**
  - N cycles over unchanged state give one digest; adding an item gives a second only after `min_gap`; and `repeat` re-sends;
  - a lookup query error files nothing;
  - two homes means the lowest number is used and audited;
  - a home is created with a milestone and without `needs-human`/`needs-ai`;
  - quoted Action lines equal the record byte for byte, and a non-bot pasted block is ignored;
  - a release-request row shows "not assigned: release-request".
- **S6:**
  - K-1 cycles file nothing, K files one, and more file no duplicate;
  - K clear cycles close it;
  - an overseer-observed condition files under `role=overseer`;
  - an unregistered key is refused;
  - the body names the command with the absolute clone path;
  - no `hos-halt`.

---

## 5. Requirement amendments (for pm-agent to record; the requirements file is not edited here)

- **AM-1 (REQ-D1, AF-1).** Replace "when a cycle ends `outcome: idle`" with "evaluated on every worker cycle, subject to REQ-D2 and a `min_gap`". `outcome: idle` misses the cheap-skip exits (`:1310`, `:1343`, `:1364`). ARCH-ESC-1.
- **AM-2 (§5 S2 sequencing, AF-5).** S2 adds no call to `escalate_to_human.sh` and no longer depends on #1934 S2. S3 does.
- **AM-3 (REQ-D3, REQ-I1, AF-2).** The standing issue and condition issues are filed into the target milestone, never milestone-less. The standing issue carries no `needs-human` and is excluded from reconcile by marker.
- **AM-4 (REQ-N6, AF-3).** "HOS-made" is decided from `assigner.login` only. A null `assigner` means not HOS-made.
- **AM-5 (REQ-N3).** For v1 the login is `HUMAN_REVIEWER` for PRs as well. CODEOWNERS-first resolution is deferred to #1936 (FU-1).
- **AM-6 (ESC-6, AF-8).** Cadences are `projects.conf` keys, not `config.sh`.
- **AM-7 (REQ-I1, AF-7).** Add the residual: conditions that stop a cycle before auth are out of reach of this mechanism.
- **AM-8 (locus, AF-4).** The deterministic core is `scripts/framework/`, protected and shipped, not `scripts/automation/lib/`.

Endorsed as written: REQ-N1, N2 (subject to ESC-1), N4, N5, N7, H1 to H4, A1 to A3, R1 to R4, D2, D4, I2, I3.

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **User-visible (requirements-sanctioned):** an assignee on `needs-human` items; reminder comments; a standing digest issue; condition issues; a stricter escalation body.
- **Not sanctioned, routed:**
  - the digest firing on busy cycles too (ARCH-ESC-1);
  - the change-triggered rate limit (ARCH-ESC-2);
  - enforcing writes at merge versus report-only first (ARCH-ESC-3);
  - a new informational label `hos-attention`, which is within ESC-5's scope and stated here.
- **Cost and operational load:** about 2 list queries per worker cycle, plus hourly per-item reads, inside a 200-call budget. There is no new service, no new credential and no new trust boundary. The worker App writes assignees, which it already can (`edit_issue.sh`).
- **Startup gap: no.** Human notification is a new requirement. NG3b's reservation of the assignee field is unchanged and respected.
- **Affected sign-offs.**
  - The #1644 T3.0a sign-off on `escalate_to_human.sh` is re-reviewed **once**, in S3, after #1934 S2 (the refusal set grows; exit codes are unchanged).
  - The NG3b design stands, and its prose is extended, not changed.
  - ADR-1934 stands. Its AD-9 block lives inside AD-8's `Action:` field.
  - ADR-1657 stands.
  - No approved design is orphaned.

---

## 7. Open human escalations

pm-agent's ESC-1 to ESC-8 stand. The architect's positions:

| ESC | Architect | Note | Gates |
|---|---|---|---|
| ESC-1 | **Concur (A).** | B adds credentials and `BOT_ACCOUNTS` entries for no notification gain. C is invisible in notifications. **Restates your acceptance criterion and needs your own-account confirmation.** | S2 |
| ESC-2 | Not a ruling. | AD-4's pre-check plus read-back make (i) irrelevant. AD-6's @mention makes (ii) and (iii) non-load-bearing. **Ask:** when S2 or S5 first runs, tell us whether you were notified by the assignment and by the digest @mention. Unverified: whether GitHub notifies on App-authored @mentions (believed yes; it is the one remaining assumption). | none |
| ESC-3 | **Concur:** remove only HOS-made. | Accept residual R-3. | S2 |
| ESC-4 | **Concur:** assign on `needs-human` PRs, digest-only reminders. | `request-reviewer` is unchanged. | S2, S4 |
| ESC-5 | **Concur:** a standing issue. | A push channel is a separate issue if you want one. | S5 |
| ESC-6 | **Concur on values,** in `projects.conf` (AM-6). | — | S4, S5, S6 |
| ESC-7 | **Concur:** #1928 owns it. | — | S6 |
| ESC-8 | **Concur** for S1, S2, S4, S5 and S6 (shipped). | S3 is HOS-only (ADR-1934 AF-1). | S1 |

Architect items, all `hard-tradeoff` under ADR-1934 REQ-3:

- **ARCH-ESC-1 (digest trigger, AF-1).** **(a)** Evaluate on every worker cycle, posting on a change or once the interval has passed, whether or not the cycle is idle. **(b)** Only on cycles that end idle, including the cheap-skip exits. Consequence of (a): you may get a digest while the pipeline is busy on other work. Consequence of (b): you are never told about a wait while unrelated work keeps the worker busy, which is the #1643/#1644 pattern. *Recommended: (a).*
- **ARCH-ESC-2 (notification volume).** A change-triggered digest is rate-limited to one per **(a)** 60 min, **(b)** 15 min (every cycle), or **(c)** none, using the 24 h repeat only. Consequence of (c): a new wait may go unannounced for up to 24 h if assignment notifications do not fire (ESC-2(ii)). *Recommended: (a).*
- **ARCH-ESC-3 (rollout).** **(a)** S2 merges with writes enabled, after you have reviewed the AD-10 dry-run report in the PR body. **(b)** S2 merges report-only, and you flip `<project>_attention_writes=1` yourself after one day of `would-*` audits. Consequence of (b): one more manual act, and one day without summons. *Recommended: (a).*

```yaml
adr: ADR-1928
issue: 1928
codable_now: [S1, S3-after-1934-S2]
design_now_merge_after: {S2: [ESC-1, ESC-3, ESC-4, ARCH-ESC-3], S4: [ESC-6], S5: [ESC-5, ARCH-ESC-1, ARCH-ESC-2], S6: [ESC-7]}
hard_constraints_not_waivable: [REQ-H1]
escalations:
  - {id: ESC-1, tier: hard-tradeoff, recommended: A, gates: [S2], note: restates human acceptance criterion}
  - {id: ESC-2, tier: hard-tradeoff, recommended: null, gates: [], note: observation request only}
  - {id: ESC-3, tier: hard-tradeoff, recommended: hos-made-only, gates: [S2]}
  - {id: ESC-4, tier: hard-tradeoff, recommended: assign-prs-digest-only, gates: [S2, S4]}
  - {id: ESC-5, tier: hard-tradeoff, recommended: standing-issue, gates: [S5]}
  - {id: ESC-6, tier: hard-tradeoff, recommended: defaults-in-projects-conf, gates: [S4, S5, S6]}
  - {id: ESC-7, tier: hard-tradeoff, recommended: 1928-owns, gates: [S6]}
  - {id: ESC-8, tier: hard-tradeoff, recommended: ship-except-S3, gates: [S1]}
  - {id: ARCH-ESC-1, tier: hard-tradeoff, options: {a: every-cycle, b: idle-only}, recommended: a, gates: [S5]}
  - {id: ARCH-ESC-2, tier: hard-tradeoff, options: {a: 60min, b: 15min, c: none}, recommended: a, gates: [S5]}
  - {id: ARCH-ESC-3, tier: hard-tradeoff, options: {a: enforce-after-report, b: report-only-then-flip}, recommended: a, gates: [S2]}
```

---

## 8. Notes and follow-ups (named, not filed here)

- **N-1 → pm-agent (AF-2).** The timeout-breaker issue (`bin/hos-cron:2193`) is filed milestone-less with `needs-ai`. While it is open, the #1395 cheap skip can never fire. This is a pre-existing defect, outside #1928.
- **FU-1.** #1936 (human-maintainers team) must revisit AD-4 step 1 (single login) and AD-5 (which login is "ours").
- **FU-2.** Make hos-cron's PR routing (`:1171-1232`) consume `next_actor`, removing the second encoding of the bounce rule (AD-11).
- **FU-3 (R-2).** Escalating pre-auth stops (usage pause, auth failure) needs a channel that does not depend on the cycle's token. Out of scope.

## Escalation flag (CORE self-flag)

RISK: HIGH. Every slice is on protected surface. S1 and S2 add the only new writer to a field NG3b uses as a security anchor. S2 adds a GitHub-dependent step to every cron cycle.
CONFIDENCE: HIGH on §0, where every citation was read in this session, and on AD-3, AD-4 and AD-5's NG3b reasoning (R4 step 0 precedes the request comment, and R5.9 requires post-dating). MEDIUM on the 200-call budget and 90 s timeout, which `technical-design` must measure. MEDIUM on ESC-2(ii) and (iii), which are deliberately made non-load-bearing.
BLAST RADIUS: assignees on open `needs-human` items in HOS and consumers (S2); one standing issue and its comments (S5); reminder comments on waiting issues (S4); condition issues (S6); every worker escalation body (S3, HOS only). No label, selection, merge or approval path changes.
Change classification: STRUCTURAL. It adds a per-cycle write step and a filing obligation. It moves no authority.

## Human Review Required

ESC-1 (restates your acceptance criterion) must be answered from your own GitHub account before S2 merges. ESC-3 to ESC-8 and ARCH-ESC-1 to ARCH-ESC-3 gate the slices named in §7. REQ-H1 is not open to any answer. For each slice, your own-account approval of the protected-surface PR is the final gate.
