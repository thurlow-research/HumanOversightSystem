# ADR-2224: A label-event workflow assigns `HUMAN_REVIEWER` when `needs-human` is applied (addendum to ADR-1928, slice 1 of #1928)

**Status:** ACCEPTED FOR DESIGN. AD-A1 to AD-A7 bind `technical-design` and `coder` for #2224. This addendum amends ADR-1928 for this slice only. The ADR-1928 file is not edited.
**Inputs:** #2224 (human request, 2026-10-30), `docs/v0.7.0/ADR-1928-next-actor-assignment.md` (AD-1, AD-3, AD-4, AD-5, AF-3, AF-6, ESC-2, ESC-3), `.github/workflows/label-swap.yml`, `scripts/framework/machine-accounts.env`, `research/findings/api-field-shape-verification.md`.
**Mandatory reviewers:** `security-reviewer` (a write token on `pull_request_target`, plus a new writer to the NG3b anchor field), `code-reviewer`, `reliability-reviewer`.

## 1. Decision

**Use a GitHub Actions workflow.** Do not build ADR-1928's cron reconcile for this slice. The workflow calls one small Python module, which is the seed of ADR-1928's `next_actor.py`.

Why the workflow and not the reconcile:
- **Coverage.** ADR-1928 AD-3 rejected per-writer hooks because they cannot see a label applied by hand. A label-event workflow does see that case: every `labeled` event fires it, whatever wrote the label. Only `GITHUB_TOKEN` writers are missed, and AD-A5 closes that gap.
- **Independence from hos-cron.** The reconcile runs only when a worker cycle runs. Suspension, `hos-halt`, a timeout-breaker trip (AF-6) or a dead host all stop it, and those are exactly the moments the human most needs a notification. The workflow runs on GitHub's side, so it covers all of them, including the breaker's own issue, with no direct call needed.
- **Latency and cost.** The workflow acts in seconds, where the reconcile waits for the next cycle (about 15 min). It needs no per-cycle API budget (ADR-1928 AD-2) and adds no step that every cycle depends on.
- **Identity.** The assigner is `github-actions[bot]`, which is a different actor from the human, so GitHub notifies them (#2224, ESC-2). The App identities need no new permission.

## 2. Decisions

### AD-A1: Module `scripts/framework/next_actor.py` (new). It contains only the AD-4 primitive and a per-item reconcile. It is ADR-1928 S1's file, seeded.
- **Language and access.** Stdlib Python plus `gh api` through `subprocess`, following the `select_work_candidates.py` pattern. Write bodies go as JSON on stdin (`--input -`). It does not import `scripts/automation/lib/github.py` (AF-4).
- **Config.** `L` and `BOT_ACCOUNTS` are parsed through `requester_trust` (`_parse_env_file` / `load_bot_accounts`). No new parser.
- **CLI.**
  - `reconcile-item --repo O/R --number N --ours <login>[,<login>…]`. It reads live state and then applies `assign` or `unassign`.
  - `assign` and `unassign` with the same arguments, for ADR-1928 S1/S2 to reuse.
  - S1 later adds the REQ-N1 pure function and `query` to this same file. It does not create a second file, and the reconcile pass (S2) imports this module rather than duplicating it.
- **Decision rule for `reconcile-item`.** The event action is not an input; only live state counts.
  - If the item is open, carries `needs-human` and does not carry `release-request`, call `assign`.
  - If `needs-human` is absent, call `unassign`.
  - Otherwise make no write.
  - Because the rule reads only live state, a run that is replaced or cancelled is harmless: the last run converges to the current state.
- **`assign` keeps ADR-1928 AD-4 steps 1 to 6 unchanged:**
  1. Resolve `L`.
  2. Assignability pre-check: `GET /assignees/{L}` must return 204.
  3. Live re-read of the issue: refuse on `release-request`; skip if the item is closed, `needs-human` is absent, or `L` is already assigned. This step gives idempotence and prevents a duplicate notification.
  4. Write with `POST /issues/{N}/assignees` and body `{"assignees":[L]}`. Never PATCH an `assignees` key. A test pins this.
  5. Read back the issue and require `L` to be among its assignees.
  6. If the read-back shows `release-request`, run `DELETE` for `L` only.
- **`unassign`.** Same live re-read, refusing on `release-request`. Then AD-A3's classification, then `DELETE /issues/{N}/assignees` for `L` only, then a read-back.
- **Writes nothing else.** No label, body or comment. A test pins that the module calls no `/labels` endpoint.
- **Exit codes.**
  - 0: done, skipped, or refused by design (`release-request`).
  - 1: transient read failure.
  - 2: usage error.
  - **3: configuration refusal** (AD-A4). This is new relative to AD-4, so a misconfiguration turns the run red rather than passing silently.
  - 4: write failed or read-back did not verify.
- **Audit.** The workflow cannot commit `audit/log`. In this slice the record is the Actions run log, where the module prints one JSON outcome line, plus GitHub's own `assigned`/`unassigned` events. The `audit_log.write_event` call is made only when the module runs inside a clone (ADR-1928 S2).

### AD-A2: Workflow `.github/workflows/needs-human-assign.yml` (new).
- **Triggers.** `issues: [opened, labeled, unlabeled]` and `pull_request_target: [opened, labeled, unlabeled]`.
- **Why `opened`.** The hos-cron breaker and broken-state paths create issues with `--label needs-human` already set. Whether GitHub also emits `labeled` on creation is not load-bearing: if both events fire, AD-A1's idempotence absorbs the second.
- **Job `if:` filter.** For `labeled`/`unlabeled`, `github.event.label.name == 'needs-human'`. For `opened`, `contains(<issue|pull_request>.labels.*.name, 'needs-human')`. Expressions in `if:` are not shell-interpolated.
- **Concurrency.** `group: needs-human-assign-<number>` with `cancel-in-progress: false`. Runs are serialized per item, and a replaced pending run is harmless (AD-A1).
- **Permissions.** `contents: read`, `issues: write`, `pull-requests: write`, and nothing else. `technical-design` drops `pull-requests: write` if a live test shows `issues: write` alone can assign on a PR.
- **Security, binding.**
  - Use one `actions/checkout@v4` step, pinned to `ref: ${{ github.event.repository.default_branch }}` (a trusted field), with `persist-credentials: false`. Optionally sparse to `scripts/framework/` only.
  - Never check out, fetch, or execute anything from the PR head or merge ref. The existing `test_gate_checkout_pinned_base.py` checks must pass, or be extended to cover this file.
  - The `run:` blocks are glue only. They pass the item number (an integer), `github.repository` and `github.token` through `env:`.
  - No `${{ }}` expression appears inside `run:`.
  - No title, body, label name, branch name or login from the event reaches a shell or a command line.

### AD-A3: "Ours" on removal = the latest `assigned` event for `L` has `assigner.login` in the `--ours` set. In this slice the set is exactly `{github-actions[bot]}`.
- **Classification.** Read `/issues/{N}/events`, paginated to completion. Take the most recent `event == "assigned"` whose `assignee.login == L`. Never read `actor`, because on these events `actor` is the assignee (AF-3).
- **Fail-safe.** A null `assigner`, a read failure or an incomplete pagination all classify as not ours, and the assignment is left alone.
- **Why only `github-actions[bot]`.** #2224 says to remove an assignment only if this mechanism made it. App-made assignments (`BOT_ACCOUNTS`) are not this mechanism, so they are left alone. No other workflow writes assignees today. A test asserts that no other `.github/workflows/*.yml` file calls an assignee endpoint, so `github-actions[bot]` as assigner means this workflow.
- **Coder obligation.** Confirm the exact `assigner.login` string from the first live event (finding #348). If the string differs, the failure mode is "never unassigns", which is fail-safe.
- **Residual from AD-5, unchanged.** If the human self-claims an item the workflow had already assigned to them, GitHub records no new `assigned` event, so the assignment is still classified as ours and is removed with the label.

### AD-A4: `L` resolution refuses rather than guesses. Confirmed, with exit 3.
- **Refuse if `L`:**
  - is empty or unset;
  - does not match the GitHub login pattern;
  - ends in `[bot]`;
  - is in `BOT_ACCOUNTS` (case-insensitive);
  - fails the assignability pre-check (404).
- **`release-request`.** The exclusion is enforced in the module on the live re-read, before every write and on every path, including `unassign`. It is not enforced only in the workflow's `if:`. The event payload is never trusted for it, and the AD-4 step 6 post-write undo is kept. NG3b's R4 step 0b applies `needs-human` to `release-request` issues itself, so this refusal is expected to fire in normal operation and returns exit 0.

### AD-A5: `GITHUB_TOKEN` label writes are covered by direct calls in `label-swap.yml`.
- **The gap.** `label-swap.yml` writes labels with `github.token`, so its events do not trigger other workflows.
- **The fix.** After the label edit in `/handoff` (adds `needs-human`) and in `/decline` (removes it), add one line of glue: `python3 scripts/framework/next_actor.py reconcile-item … --ours github-actions[bot]`, best-effort (`|| echo "::warning::…"`). The command's behaviour and exit stay unchanged otherwise.
- **The assigner stays the same.** Both workflows use `github.token`, so the assigner is `github-actions[bot]` and AD-A3 holds for both.
- No other workflow writes labels today (checked by grep).

### AD-A6: No backfill. No consumer shipping in this slice.
- **No backfill.** There is no sweep, and existing labelled items are untouched. Only new events cause writes (#2224 R5). That rule does not survive ADR-1928 S2: the cron reconcile would backfill by construction, so S2 must re-raise the backfill question with the human.
- **Not shipped.** Neither the workflow nor the module is added to `framework_consumer_files.txt`. A consumer-side workflow would change consumers' notification behaviour, which is a product consequence for them. Nothing installed in a consumer calls the module yet. The AD-1 shipping obligation moves to the slice that adds the first consumer caller (ADR-1928 S2).

### AD-A7: How this addendum amends ADR-1928.
- **AD-1.** "No other code writes an assignee except `edit_issue.sh`" now also allows `next_actor.py`, called from `needs-human-assign.yml` and `label-swap.yml`. Those are the module's only callers until S2.
- **AD-3.** The workflow is now primary coverage. When S2 is built, the reconcile becomes a backstop for outages and missed events. The AF-6 breaker direct call is dropped, because the workflow sees the breaker's App-created issue.
- **AD-5.** S2 must pass `--ours` = `BOT_ACCOUNTS ∪ {github-actions[bot]}`, so that each mechanism recognises the other's assignments. Otherwise the reconcile would never clean up after a missed `unlabeled` event.
- **Unchanged.** AD-4, AD-9 and NG3b R1 to R5 are unchanged.
- **Startup gap:** no. This is a new human request that post-dates ADR-1928.
- **Affected sign-offs:** none. Nothing from ADR-1928 is built.

## 3. Slice files (7, or 8 if regeneration touches CODEOWNERS)
1. `.github/workflows/needs-human-assign.yml` (new)
2. `scripts/framework/next_actor.py` (new)
3. `tests/framework/test_next_actor.py` (new): fake `gh`. Covers assign, skip-if-assigned, release-request refusal on every path, the post-write undo, PATCH forbidden, no `/labels` calls, the classification table (assigner ours / human / App bot / null / `actor` = bot with assigner = human), and every exit-3 case.
4. `tests/framework/test_needs_human_assign_workflow.py` (new), static checks:
   - triggers and the `if:` filter;
   - checkout pinned to the default branch with `persist-credentials: false`;
   - no `${{` inside `run:`;
   - the permissions block;
   - no other workflow writes assignees;
   - `label-swap.yml` calls the module in `/handoff` and `/decline`.
5. `.github/workflows/label-swap.yml` (AD-A5 glue)
6. `docs/LABELS.md`: in the `needs-human` row, add the assignment side effect and the AD-9 sentence that an assignment is a notification only.
7. `SCRIPTS-INDEX.md` (regenerated). Run `regen_all.sh --check`; if CODEOWNERS changes, it is file 8.

## 4. Residuals (stated, accepted)
- **R1.** A future `GITHUB_TOKEN` label writer other than `label-swap.yml` would be missed. The AD-A2 test fails if a new workflow writes assignees, but it cannot detect a new label writer. Mitigation: the ADR-1928 S2 backstop.
- **R2.** The self-claim residual from AD-A3.
- **R3.** The behaviour can only be checked live after merge. Workflows on `issues` and `pull_request_target` run from the default branch, so pre-merge evidence is tests only. The human confirms one real notification after merge (ESC-2).
- **R4.** Actions outages drop events, with no retry until S2 exists.
- **R5.** The ~100 existing items stay unassigned (no backfill, by request).

## Escalation flag (CORE self-flag)
RISK: HIGH. Protected surface (`.github/workflows/**`, `scripts/framework/**`). Adds a `pull_request_target` job holding a write token, and a writer to the NG3b anchor field.
CONFIDENCE: HIGH on the mechanism choice and the NG3b guard, because AD-4 is reused intact. MEDIUM on two points that live behaviour settles: whether `opened` also emits `labeled` (not load-bearing), and whether PR assignment needs `pull-requests: write`.
BLAST RADIUS: One repo (not shipped). It writes only `L`'s assignee entry on items labelled `needs-human`. When it fails, it either skips the write or turns the run red. No gate reads these assignments.

## Human Review Required
Protected-surface approval at merge, which is already required. Nothing else is gated before merge: the human asked for this behaviour, and the product-boundary checkpoint is cleared by #2224 itself. After merge, ESC-2 asks the human to confirm one notification. That is an observation, not a gate.
