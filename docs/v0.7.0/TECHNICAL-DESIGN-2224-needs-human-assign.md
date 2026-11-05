# TECHNICAL-DESIGN-2224: Assign `HUMAN_REVIEWER` when `needs-human` is applied (#2224, slice 1 of #1928)

**Status:** DRAFT, awaiting architect review (round 1). **Binding inputs:** `ADR-2224-needs-human-assign-workflow.md` (AD-A1 to AD-A7), `ADR-1928-next-actor-assignment.md` AD-4, AD-5, AF-3, §4 S1 test obligations, as amended by ADR-2224. Where the two ADRs differ, ADR-2224 governs. This document fixes the contract; it contains no implementation.
**Change class:** additive. No code built against ADR-1928, so no sign-off is affected and there is no startup gap (ADR-2224 AD-A7).

## 1. `scripts/framework/next_actor.py` (new, stdlib + `gh` only)

### 1.1 Imports and invocation
- **Invocation:** `python3 scripts/framework/next_actor.py <subcommand> …` from the checkout root (the ADR-2224 AD-A5 literal form). Before importing `scripts.framework.*`, the module inserts `Path(__file__).resolve().parents[2]` at `sys.path[0]` if absent, as `require_overseer_approval.py:229-236` does. `python3 -m scripts.framework.next_actor` must also work (precedent `bin/hos-cron:1432`).
- **Config parser, decided:** reuse `scripts/framework/requester_trust.py`: `_parse_env_file` (`:242`), `_machine_accounts_path` (`:206`), `machine_accounts_file_absent` (`:214`), `load_bot_accounts` (`:301`). `requester_trust` imports only stdlib plus `require_human_approval` (itself stdlib-only), so it runs on a bare Actions runner.
- **Rejected:** `scripts/automation/lib/merge_config.py`. It imports `merge_authority`, which imports `scripts/automation/lib/github.py` (forbidden by AF-4). It also fails unless all six AD-9 keys are present. No other `=`-splitting code is allowed in `next_actor.py`.
- **Not imported:** `scripts/automation/**` (AF-4). `scripts/oversight/lib/audit_log.py` is also not imported: it writes `audit/log` files in a clone, and an Actions runner cannot commit them. The audit record is the Actions run log plus GitHub's `assigned`/`unassigned` events (AD-A1). The audit call is added in ADR-1928 S2.

### 1.2 CLI (argparse, subparsers required)
| Subcommand | Args (all required) |
|---|---|
| `reconcile-item` | `--repo O/R --number N --ours LOGIN[,LOGIN…]` |
| `assign` | `--repo O/R --number N` (`--ours` is accepted and ignored, so all three share one parent parser) |
| `unassign` | `--repo O/R --number N --ours LOGIN[,LOGIN…]` |

Validation:
- `--repo` must match `^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$`.
- `--number` must be an integer ≥ 1.
- Each `--ours` entry must match `^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(\[bot\])?$`. The set is lowercased and must not be empty.

Any violation, or an unknown or missing subcommand, gives **exit 2** (argparse's own exit 2 is acceptable) and makes no `gh` call.

**Exit codes (AD-A1):**
- 0: done, skipped, or refused by design.
- 1: transient read failure.
- 2: usage error.
- 3: configuration refusal.
- 4: write failed or read-back did not verify.

**Output:** exactly one JSON line on stdout: `{"op":…,"repo":…,"number":N,"login":L|null,"outcome":"<token>","exit":n}`. When exit ≠ 0, or the outcome is `ng3b-race-undone`, the module also writes one `::warning::next_actor <outcome> #N` line to stderr. Never print issue titles, bodies or label lists.

### 1.3 Functions (public names fixed; tests import them)
- `_gh(method, path, body=None) -> (status:int, payload)`.
  - This is the **only** `subprocess.run` call site.
  - argv: `["gh","api","--include"]`, plus `["--method",method]` when the method is not GET, then `path`, plus `["--input","-"]` when `body` is not None. The body goes as `input=json.dumps(body)` with `text=True`, `capture_output=True`, `check=False` and `timeout=30`.
  - The HTTP status is parsed from the `--include` header block exactly as `rerun_gate_checks.py:79-130` does (CRLF or LF split, `HTTP/\S+\s+(\d+)`).
  - It returns `(0, None)` on OSError, a timeout, or an unparseable status, and never raises on an HTTP status.
  - The JSON body is parsed if it is non-empty. Otherwise the payload is None.
- `resolve_login(repo_root) -> str`. Raises `ConfigRefusal(token)`, which the CLI maps to exit 3 (AD-A4), with these tokens:

  | Condition | Token |
  |---|---|
  | `machine_accounts_file_absent` | `next-actor-unresolved:config-absent` |
  | `HUMAN_REVIEWER` missing or empty after `.strip()` | `…:unset` |
  | Not matching `^[A-Za-z0-9](?:[A-Za-z0-9]\|-(?=[A-Za-z0-9])){0,38}$` | `…:bad-login` |
  | Ends in `[bot]` (case-insensitive) | `…:bot-suffix` |
  | `lower()` in `load_bot_accounts(repo_root)` | `…:bot-account` |

  The CLI's `repo_root` is `Path(__file__).resolve().parents[2]`, which is the trusted checkout. `HUMAN_REVIEWER` is read from that file only; no environment variable or CLI flag may override it (the environment may only widen `BOT_ACCOUNTS`, per `load_bot_accounts`' union rule).
- `check_assignable(repo, L)`: `GET repos/{repo}/assignees/{L}`.
  - 204: proceed.
  - 404: `ConfigRefusal("next-actor-unresolved:not-assignable")`, exit 3.
  - Anything else: outcome `assign-failed:precheck`, **exit 1** (it is a read).
- `read_item(repo, N) -> Item | None`: `GET repos/{repo}/issues/{N}`. This works for PRs too.
  - A status other than 200, or a non-dict payload, returns None and the caller exits 1 with `read-failed`.
  - `Item` holds `state`, `labels` (a set of label names), and `assignees` (a set of lowercased logins).
- `classify_ours(repo, N, L, ours) -> (bool, reason)`. AD-A3 is defined in §1.5.
- `assign(repo, N, L) -> (outcome, exit)`, `unassign(repo, N, L, ours) -> (outcome, exit)`, and `reconcile_item(repo, N, L, ours) -> (outcome, exit)`. The CLI calls `resolve_login` first, on every subcommand, before any `gh` call.

### 1.4 Exact call sequences (paths have no leading slash; L is compared case-insensitively)
**`assign`** (AD-4 steps 2 to 6; step 1 is `resolve_login`):
1. `GET repos/{repo}/assignees/{L}` (as in §1.3).
2. `GET repos/{repo}/issues/{N}`. Read failure: exit 1. Then:
   - `release-request` in labels: `next-actor-refused:release-request`, exit 0.
   - The item is not open: `next-actor-skip:closed`.
   - `needs-human` is not in labels: `next-actor-skip:label-absent`.
   - L is already in assignees: `next-actor-skip:already-assigned`.

   Every case above ends with no further call and exit 0.
3. `POST repos/{repo}/issues/{N}/assignees` with stdin `{"assignees":["<L as configured>"]}`. A non-2xx status gives `assign-failed:write`, exit 4.
4. `GET repos/{repo}/issues/{N}` (read-back). If the read fails: `assign-unverified`, exit 4.
5. If the read-back labels contain `release-request`:
   - If L is in assignees: `DELETE repos/{repo}/issues/{N}/assignees` with stdin `{"assignees":[L]}`, then `GET` issue. If L is no longer in assignees: `ng3b-race-undone`, exit 0. If the DELETE returned non-2xx or L is still assigned: `ng3b-race-undo-failed`, exit 4.
   - If L is not in assignees: `ng3b-race-noop`, exit 0.
6. Otherwise, if L is not in the read-back assignees: `assign-unverified`, exit 4. If L is present: `assigned`, exit 0.

**`unassign`** (there is no assignability pre-check):
1. `GET` issue. Read failure: exit 1. Then:
   - `release-request` present: `next-actor-refused:release-request`, exit 0, with **no events read and no assignee call**.
   - `needs-human` present: `unassign-skip:label-present`, exit 0.
   - L is not in assignees: `unassign-skip:not-assigned`, exit 0.
   - A **closed item is not skipped**, because `/decline` closes as well as removing the label.
2. Run `classify_ours`.
   - Events read failure: `unassign-skip:events-read-failed`, **exit 1**, with no write.
   - Not ours for any other reason: `unassign-skip:not-ours:<reason>`, exit 0.
3. `DELETE repos/{repo}/issues/{N}/assignees` with stdin `{"assignees":[L]}`. The list contains L only and never another login. A non-2xx status gives `unassign-failed:write`, exit 4.
4. `GET` issue. If L is still assigned, or the read fails: `unassign-unverified`, exit 4. Otherwise `unassigned`, exit 0.

**`reconcile-item`.** The event action is never an input; only live state counts.
1. `GET` issue (read failure: exit 1).
2. Decide from that state:
   - Open, `needs-human` present, `release-request` absent: return `assign(...)`, which performs its own live re-read.
   - `needs-human` absent: return `unassign(...)`.
   - Otherwise: `reconcile-noop:<closed|release-request>`, exit 0, with no further call.

**Forbidden in the module source** (each is pinned by a test):
- the string `PATCH`;
- any path containing `/labels`, `/comments` or `/events` used with a non-GET method;
- any import from `scripts.automation`.

### 1.5 "Ours" classification (AD-A3, AF-3)
1. Fetch `GET repos/{repo}/issues/{N}/events?per_page=100&page={k}` for k = 1 to `EVENTS_PAGE_BOUND = 10`, one `gh` call per page (no `--paginate`; precedent `select_work_candidates.py:297-319`).
2. Each page must return status 200 with a list payload. Anything else is a read failure.
3. A page with fewer than 100 items ends the history (COMPLETE).
4. If page 10 is full, the result is BOUND-REACHED, which gives not ours with reason `events-incomplete` (exit 0, no write).
5. Candidates are events with `event == "assigned"` and `(assignee or {}).get("login","").lower() == L.lower()`. The latest is the one with the greatest `(created_at, id)`. Events missing `created_at` are ignored.
6. Ours iff the latest candidate's `assigner` is a dict with a non-empty `login` whose `lower()` is in `ours`. `actor` is **never read**.
7. Reasons: `no-assigned-event`, `assigner-null`, `assigner-not-ours`, `events-incomplete`. The `--ours` set for this slice is exactly `github-actions[bot]`.
8. Coder obligation (finding #348): after merge, confirm the live `assigner.login` string on the first workflow-made `assigned` event, and record it in the PR or on #2224. If the string differs, the failure is "never unassigns", which is fail-safe.

## 2. `.github/workflows/needs-human-assign.yml` (new)
| Key | Exact value |
|---|---|
| `on` | `issues: {types: [opened, labeled, unlabeled]}` and `pull_request_target: {types: [opened, labeled, unlabeled]}`. No other trigger and no `branches` filter. |
| top-level `permissions` | `contents: read`, `issues: write`, `pull-requests: write`, nothing else, and no job-level `permissions`. `pull-requests: write` is **kept**: the ADR's drop condition needs a live test that cannot run before merge (R3). Dropping it later is a follow-up. |
| `concurrency` | `group: needs-human-assign-${{ github.event.issue.number \|\| github.event.pull_request.number }}`, `cancel-in-progress: false` |
| job `needs-human-assign` | `runs-on: ubuntu-latest`, `timeout-minutes: 5` |
| job `if:` | `((github.event.action == 'labeled' \|\| github.event.action == 'unlabeled') && github.event.label.name == 'needs-human') \|\| (github.event.action == 'opened' && (contains(github.event.issue.labels.*.name, 'needs-human') \|\| contains(github.event.pull_request.labels.*.name, 'needs-human')))` |
| step 1 | `uses: actions/checkout@v4` with `ref: ${{ github.event.repository.default_branch }}` and `persist-credentials: false`. **No sparse checkout:** the import needs `scripts/__init__.py`, and cone mode would omit it. |
| step 2 `env:` | `GH_TOKEN: ${{ github.token }}`, `REPO: ${{ github.repository }}`, `ITEM_NUMBER: ${{ github.event.issue.number \|\| github.event.pull_request.number }}`. There are no other env keys. |
| step 2 `run:` | `python3 scripts/framework/next_actor.py reconcile-item --repo "$REPO" --number "$ITEM_NUMBER" --ours 'github-actions[bot]'` |

Other rules for this file:
- No other steps. No `${{` inside any `run:`. No `git fetch`, `gh pr checkout`, `head.sha`, `head.ref` or `refs/pull/` anywhere in the step values.
- The non-zero exit is **not** suppressed, so exits 1, 3 and 4 turn the run red.
- The header comment states the security model: trusted default-branch code, data read only through the API, no event text in the shell. The header must not use the strings the tests forbid in step values.

## 3. `.github/workflows/label-swap.yml` (AD-A5 glue: two inserted lines, nothing else changes)
Insert the line below immediately after the `gh issue edit … --remove-label "needs-human" --add-label "wontfix" … || true` line in the `/decline` branch. Insert it again immediately after the `gh issue edit … --remove-label "needs-ai" --add-label "needs-human" … || true` line in `/handoff`:

```
python3 scripts/framework/next_actor.py reconcile-item --repo "$GITHUB_REPOSITORY" --number "$ISSUE_NUMBER" --ours 'github-actions[bot]' || echo "::warning::next_actor reconcile-item exited $?; assignment not updated"
```

- `$GITHUB_REPOSITORY` is the runner's default env, and `$ISSUE_NUMBER` already exists, so no new `${{ }}` is added.
- The `|| echo` keeps `set -euo pipefail` from failing the step. Every existing line, the permissions (`contents: read`, `issues: write`, which suffice because `label-swap` is issues-only), the checkout and the comments stay byte-identical.
- The existing pins (`test_selection_call_sites.py:156-181`) must still pass. The glue sits after the `/approve` `else`, so the `/approve` branch slice is unaffected.

## 4. `docs/LABELS.md`
Append the text below to the **notes cell of the existing single `| \`needs-human\` |` row**, on the same physical line. `test_overseer_approval_merge_wiring.py:133-137` requires exactly one row and the existing phrases. Do not change the writers column, because the workflow writes no label.

> **Assignment side effect (#2224, ADR-2224).** When `needs-human` is applied to an open issue or PR, by any actor, `.github/workflows/needs-human-assign.yml` assigns `HUMAN_REVIEWER` through `scripts/framework/next_actor.py`, so GitHub notifies the human. `label-swap.yml` `/handoff` and `/decline` call the same module directly, because their `GITHUB_TOKEN` label writes trigger no workflow. Removing the label removes that assignment only if `github-actions[bot]` made it; assignments by anyone else are left alone. `release-request` issues are never assigned or unassigned by this mechanism (NG3b). There is no backfill: items labelled before this change landed stay unassigned. The assignment is a notification only. It authorizes nothing, and no gate reads it (ADR-1928 AD-9).

## 5. Test plan (deterministic; no network)
**`tests/framework/test_next_actor.py`.**
- Fixtures: a `FakeGh` replaces `next_actor._gh` through `monkeypatch`, routes `(method, path)` to queued `(status, payload)` pairs, records every `(method, path, body)` call, and fails the test on an unrouted call. A `tmp_path` repo root holds `scripts/framework/machine-accounts.env`. `BOT_ACCOUNTS` is cleared through `monkeypatch.delenv` unless a test sets it.
- Config, exit 3, zero gh calls: `test_refuse_config_absent`, `test_refuse_unset`, `test_refuse_empty`, `test_refuse_bad_login[Scott Thurlow,-x,a/b,40-char]`, `test_refuse_bot_suffix`, `test_refuse_bot_accounts_member_case_insensitive` (env `BOT_ACCOUNTS=alice`, `HUMAN_REVIEWER=Alice`).
- Pre-check: `test_not_assignable_404_exit3_no_write`, `test_precheck_500_exit1_no_write`.
- Assign:
  - `test_assign_call_sequence_exact`. The recorded calls equal GET assignees/L, GET issue, POST assignees with `{"assignees":["ScottThurlow"]}`, GET issue. Exit 0, `assigned`.
  - `test_assign_skip_already_assigned_case_insensitive`, `test_assign_skip_closed` and `test_assign_skip_label_absent`. Each makes no POST.
  - `test_assign_refuse_release_request_no_assignee_call`.
  - `test_assign_unverified_when_login_dropped` (exit 4), `test_assign_write_non2xx_exit4`, `test_assign_reread_failure_exit1`.
  - `test_post_write_release_request_undo_one_delete`. The read-back shows `release-request` and L. The test asserts exactly one DELETE, with body `{"assignees":[L]}`, then one GET, and no other writes. Exit 0, `ng3b-race-undone`.
  - `test_post_write_undo_failure_exit4`.
- Unassign:
  - `test_unassign_ours_deletes_only_L` (assignees [L, `other`]; the DELETE body is exactly [L]).
  - `test_unassign_refuse_release_request_no_events_no_assignee_call`.
  - `test_unassign_skip_label_present`, `test_unassign_skip_not_assigned`, `test_unassign_proceeds_when_closed`, `test_unassign_unverified_exit4`, `test_unassign_events_read_failure_exit1_no_write`.
- Classification (parametrized `test_classify_ours`), one case per row: assigner `github-actions[bot]` → ours; assigner `ScottThurlow`, `hos-worker-hos[bot]`, null, or key absent → not ours; `actor=github-actions[bot]` with `assigner=ScottThurlow` → not ours (AF-3); older ours then newer human → not ours; older human then newer ours → ours; an event for another assignee is ignored; no event → `no-assigned-event`.
- Pagination: `test_events_complete_across_two_pages` (100 + 5 events, ours on page 2) and `test_events_bound_reached_not_ours_no_delete` (10 full pages; exit 0; exactly 10 events GETs).
- Reconcile:
  - `test_reconcile_open_labelled_assigns`, `test_reconcile_label_absent_unassigns`, `test_reconcile_closed_labelled_noop`, `test_reconcile_release_request_labelled_noop_no_assignee_call`.
  - `test_reconcile_second_run_zero_writes` (idempotent).
  - `test_direct_function_calls_refuse_release_request` (NG3b: `assign()` and `unassign()` called directly).
- CLI and `_gh`:
  - `test_cli_usage_exit2[missing --number, --number 0, --number x, bad --repo, bad --ours, unknown subcommand]`, which also asserts no gh call.
  - `test_cli_prints_exactly_one_json_line`.
  - `test_gh_argv_post_uses_input_stdin`. This monkeypatches `subprocess.run` and asserts argv `["gh","api","--include","--method","POST",path,"--input","-"]` and `input` equal to the JSON.
  - `test_gh_parses_status_crlf_and_lf` and `test_gh_timeout_returns_zero`.
- Static checks on the module source:
  - `test_single_subprocess_call_site`.
  - `test_no_patch_anywhere` (the AST and the source contain no `PATCH` string).
  - `test_no_labels_comments_or_write_events_paths`.
  - `test_no_scripts_automation_import`.
  - `test_config_via_requester_trust_only`. It imports `_parse_env_file` and `load_bot_accounts` from `requester_trust`, and the source has no `partition("=")` or `split("=")`.

**`tests/framework/test_needs_human_assign_workflow.py`.** It parses YAML with `yaml.safe_load` and takes the `on` key as `True`, as `test_gate_checkout_pinned_base.py:54-56` does.
- `test_triggers_exact`.
- `test_job_if_filters_needs_human`, which asserts both the action branches and the `'needs-human'` literal.
- `test_permissions_exact_and_no_job_permissions`.
- `test_concurrency_group_and_no_cancel`.
- `test_single_checkout_pinned_default_branch_no_credentials` (ref string equality; `persist-credentials is False`).
- `test_no_pr_head_or_merge_ref_in_step_values`.
- `test_no_expression_inside_run[needs-human-assign.yml,label-swap.yml]`.
- `test_env_keys_and_values_exact`.
- `test_run_command_exact`.
- `test_no_other_workflow_writes_assignees`. No `.github/workflows/*.yml` contains `/assignees`, `--add-assignee`, `--remove-assignee` or `--assignee`, and only `needs-human-assign.yml` and `label-swap.yml` contain `next_actor.py`.
- `test_label_swap_calls_module_in_decline_and_handoff_best_effort`. In each `case` branch's slice, the glue line follows that branch's `gh issue edit` line and ends in `|| echo "::warning::`.
- `test_label_swap_permissions_unchanged`.
- `test_not_shipped`. Neither workflow nor `next_actor.py` appears in `framework_consumer_files.txt`.

## 6. Files (8) and generated artifacts
1. `scripts/framework/next_actor.py` (new)
2. `.github/workflows/needs-human-assign.yml` (new)
3. `.github/workflows/label-swap.yml`
4. `tests/framework/test_next_actor.py` (new)
5. `tests/framework/test_needs_human_assign_workflow.py` (new)
6. `docs/LABELS.md`
7. `SCRIPTS-INDEX.md`, regenerated through `scripts/framework/regen_all.sh`. `gen_scripts_index.sh` takes the first docstring paragraph of each `scripts/**/*.py`, so a new line is added for `next_actor.py`, and `tests/framework/test_scripts_index.py` fails until the index is regenerated. The module docstring's first paragraph must be one sentence.
8. This document.

Files that do not change:
- **`.github/CODEOWNERS`.** The globs `scripts/framework/**` and `.github/workflows/**` already cover the new files (`protected_surfaces.txt`). `regen_all.sh --check` should therefore report only SCRIPTS-INDEX as stale.
- **`framework_consumer_files.txt`** (AD-A6, not shipped).
- **A `prompts/` mirror** is not needed. Only `select_work_candidates.py` and `setup_branch_protection.sh` have mirrors under `prompts/scripts/framework/`; `rerun_gate_checks.py`, `require_*` and `requester_trust.py` have none. The contract (`OVERSIGHT-CONTRACT.md:159`, evaluator `:513ff`) accepts a `Prompt-Artifact:` trailer that points at a technical-design section. The coder's commits carry `Prompt-Artifact: docs/v0.7.0/TECHNICAL-DESIGN-2224-needs-human-assign.md`.

## 7. Boundaries
- The module writes only L's assignee entry, through POST or DELETE on `/assignees`, and nothing else.
- It never trusts the event payload for `release-request`, labels or state.
- There is no backfill path: no listing or sweep subcommand exists.
- Behaviour can only be observed live after merge (R3). The human confirms one notification (ESC-2), and the coder confirms the `assigner.login` string (§1.5, step 8).

## Escalation flag
RISK: HIGH. Protected surfaces (`.github/workflows/**`, `scripts/framework/**`): a `pull_request_target` job with a write token, and a new writer to the NG3b anchor field. CONFIDENCE: HIGH on the call sequences and the NG3b guard (AD-4 reused intact). MEDIUM on two points only live behaviour settles: the exact `assigner.login` string and whether `issues: write` alone suffices for PRs. Change class: additive.

## Human Review Required
Protected-surface approval at merge, which is already required. Mandatory reviewers: `security-reviewer`, `code-reviewer`, `reliability-reviewer`.
