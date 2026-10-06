# ADR-1935: Protected-surface recalibration. Classify by what a file decides, not where it lives

**Status:** ACCEPTED FOR DESIGN. The classification rule (§2), the inventory (§3) and the list (§4) are binding technical rulings. **The list change does not take effect until ESC-1 (§7) clears**, because it raises the human-approval load (a product/operational consequence; architect CORE, product-boundary checkpoint).
**Date:** 2026-10-06
**Author:** architect
**Issue:** #1935. Also closes the two items TD-1643 Amendment E §E.10 Q2 routed here (#1932): (a) `scripts/run_second_review.sh`, (b) `.hos-manifest`.
**Verified against:** `main` @ `1b4242033`. All file facts below were read from the tree, not inferred from names.
**Consumers:** `technical-design` → `coder` (the implementing PR), `security-reviewer`, the CODEOWNERS human gate.
**Out of scope:** issue item 3 (a codeowner for the unprotected remainder). That question belongs to epic #1936, which depends on this classification. **No machine account is added to CODEOWNERS** (#1816/#1819/#1820: a bot approval must never satisfy the gate that guards the controls constraining the bot).

---

## 1. Findings

**AF-1 (HIGH): the issue's premise does not hold. Over-breadth is not what drives the gate rate.**
I measured every PR merge on `main` since 2026-08-15 (123 merges; first-parent, `(#N)`/merge-PR subjects):

| | Server-side protected | Human-routed (protected OR `security_surfaces.txt`) |
|---|---|---|
| Current list | 45/123 (37%) | 53/123 (43%), which matches the issue's "~45%" |
| This ADR's list | 59/123 (48%) | 60/123 (49%) |

- Only **one** of the 45 current hits is caused solely by a file this ADR unprotects: `0eabb8685`, `bootstrap/edit_issue_edges.sh`. In every other `bootstrap/**` hit, another protected file was touched as well.
- The 14 merges the new list adds all change real controls. Examples: `d6c1392a6` (#1737, "never default to approve" in second-review verdict aggregation), `941c72c4b` (#1643 W5a, the shared posture security control), `a4c128817` (#1759, `changeset.sh`, which decides which files every gate scans), and `066a44c20` (the release-panel exclusion list).
- **Consequence:** no correct classification lowers the human load. Recalibration increases it by about 6 points. Load relief has to come from #1936 or somewhere else. This is ESC-1.

**AF-2 (HIGH): the under-coverage is larger than the issue lists.** The following files decide or feed an approve, merge, escalate or pass outcome, and **no server-side check protects them today:**
- `merge_authority.py` and its CLI, `merge_config.py`, `pr_review_cli.py`.
- `agent_invoke_cli.py` and `posture.py` (the agent tool posture).
- `dimension_registry.py` and its CLI (the required-review set).
- `second_review_logic.py` and `validation_logic.py`.
  - *Path correction:* `validation_logic.py` is in `scripts/oversight/`, not `scripts/automation/lib/`.
- `run_second_review.sh` and `run_review_chain.sh`.
- `lib/changeset.sh` and `changeset_logic.py`: they decide which files the gates scan.
- `suspension_manager.py`: gate suspension, run inside `run_gates.sh`.
- `ensure_venv.sh`: every gate **sources** it, and it sets `OVERSIGHT_PYTHON`/`VENV_BIN`.
- `validators/rn_calculator.py`: it is the **only** score input to the server-side `require-tier-ceiling` check (`require_tier_ceiling.py:225-266`).
- The release-gate logic and the release-panel logic.

`security_surfaces.txt` already routes `scripts/automation/lib/**` to HUMAN_REQUIRED. That routing lives in the overseer's own client-side matrix. It is not server-side, and it does not cover the CLIs or `scripts/oversight/`.

**AF-3 (HIGH, corrects the issue): `bootstrap/query_issues.sh` is not over-protected.**
- `contract/dimensions/postures/review-read-only-gh-read.settings.json` grants `Bash(bootstrap/query_issues.sh *)` **by name**, inside a deny-by-default review posture.
- ADR-1643 Amendment 5 §10.2 says the permission boundary has been delegated to the script's own argument handling, and that this surface "is small, human-gated and reviewed once".
- Unprotecting it would let a bot-approved change give a read-only reviewer session write capability, without anyone noticing. It stays protected (rule P4).

**AF-4: what the gate can and cannot protect.**
- `apps.env` holds the worker, overseer and human App PEMs. The cron worker runs under `--permission-mode bypassPermissions` (`bin/hos-cron:1922`).
- Any repo code that Worker or Overseer executes therefore already has full credential reach. The protected-surface gate is not, and cannot be, a code-execution boundary.
- What it guards is narrower and real: **a rule that constrains a bot is never changed on a bot's approval.** That is why the rule below protects decision logic and its trusted dependencies, and not transport.

**AF-5: guarantees in other ADRs rest on directory coverage.** These were found by grepping for `bootstrap/**`, `bin/**`, `scripts/framework/**`, `protected_surfaces` and "protected surface":
- ADR-1540 AF-3 places the trust gate in `scripts/framework/` *so that* it is protected.
- ADR-035, ADR-036, ADR-038 and ADR-1221 do the same.
- ADR-1944 AF-2 relies on `bin/**`.
- ADR-1542 Q4 relies on "adding a named operation is a `bootstrap/**` PR".
- ADR-1643 A5 relies on `query_issues.sh`.

§5.2 audits each one. None is removed silently.

**AF-6: two tests encode the old list, and both are ratchets that are working as designed.**
- `test_t5_63_…` fails as intended (TD-D42).
- `test_near_misses_do_not_match` lists `validators/rn_calculator.py` and `scripts/run_second_review.sh` as must-not-match.
- Both fail against §4 (verified on an exported tree). So do `test_codeowners_current.py` and `test_regen_all.py` until CODEOWNERS is regenerated. After regeneration they pass.
- Nothing else in the 12 protected-surface-related test files fails. A full inner-loop run showed one unrelated flake (`test_agent_invoke_wrapper.py`), which passed on rerun under both lists.

**AF-7: `protected_surfaces.txt` ships verbatim to consumers** (`framework_consumer_files.txt:61`; overwritten on upgrade).
- Some HOS-repo files are controls in HOS but live in namespaces that consumers own: `pyproject.toml` (flake8 and coverage thresholds), `tests/conftest.py`, `.claude/settings.json` (merged into consumers) and `.claude/commands/**`.
- Listing them would put a human gate on consumers' own application files. They are **excluded** (residual R-2), so this ADR makes no consumer-facing change beyond HOS-owned files.

---

## 2. Classification rule (binding)

A tracked file is **PROTECTED** if any of P1–P4 holds. Otherwise it is **UNPROTECTED**, and the inventory row names which of N1–N3 applies.

- **P1 — Defines or enforces a control.** "Control" means any of:
  - merge authority, approval, or review-verdict computation, including which reviewers or sign-offs are required;
  - credential, token or identity: minting, revoking, identity guards, bot-account sets, ceilings;
  - agent definitions and governance text, including cron prompts;
  - release gating;
  - gate or validator outcome computation (pass/fail, score, tier, suppression);
  - cron enable, halt, suspend, budget and usage-pause;
  - branch ownership and PR-opening refusal;
  - CODEOWNERS / protected-surface / sandbox-policy generation;
  - the installer path that ships any of the above to consumers (ship-sets, CORE-region rewriting).
- **P2 — In-process dependency of a PROTECTED file.**
  - This covers a Python `import` (including every package `__init__.py` on the import path), an `importlib` path load, and a shell `source`/`.`.
  - Code in the same process can rewrite the importer at load time, so trust is transitive.
  - **There are no exemptions.** P2 applies even to "pure transport" libraries such as `github.py` or `audit_log.py`.
- **P3 — Decision input of a PROTECTED file.** This is a subprocess, data file or configuration file whose exit code, output or content a PROTECTED file consumes to decide a control outcome. Examples:
  - pass or fail;
  - approve, merge or escalate;
  - tier;
  - which files are checked;
  - which findings are suppressed;
  - which tool version computes a verdict;
  - halt or continue.
- **P4 — Named permission grant.** The file is named individually in an allow rule of a tracked *restrictive* (deny-by-default) posture. Today that means `contract/dimensions/postures/*.settings.json`; the future ADR-1542 FR-8 role templates will also qualify.
  - The file's content then *is* that rule's capability.
  - Wildcard grants (`Bash(bootstrap/*)`) and entries in permissive policies that already grant the same capability through broader rules (`.claude/settings.json`'s `gh pr:*`) do **not** trigger P4.

UNPROTECTED reasons:
- **N1 — Transport.**
  - The file performs an action the caller's App token already permits, and decides nothing (issue, comment, label, edge and review-thread wrappers).
  - Or it is a subprocess callee whose result no PROTECTED file consumes as a decision input (`|| true` audit writes, best-effort sync, usage records).
- **N2 — Unreachable.** Nothing calls the file: not `bin/`, not a workflow, not a cron prompt, not an agent definition, not a PROTECTED file.
- **N3 — Evidence or advisory.** The file is either:
  - a record that a PROTECTED check re-verifies or that a human reads; or
  - a tool or document whose output only a human consumes.

**The transitive question.** Protection flows **downward** from a protected file to what it trusts (P2, P3, P4). It never flows **upward** to the file's callers.
- `get_app_token.sh` is P1, because it is identity.
- `create_issue.sh` *calls* `get_app_token.sh`. That makes it a caller, not a callee, so it stays N1. A modified wrapper can only do what the minted token already allows, and AF-4 explains why that is not the gate's job.
- `github.py` is P2. `decide_merge_authority()` imports it in-process and reads PR reviews through it, so a modified `github.py` can change the reviews the merge decision sees.

**Tie-breaker.** If P3 is arguable and the file's output can flip an approve, merge, escalate or pass outcome, it is PROTECTED.

**Directory homes.**
- `bin/` and `scripts/framework/` stay whole-directory (`**`).
  - Every launcher is a control.
  - `scripts/framework/` is the ratified place to put new control code, so that the code is protected by construction (ADR-1540 AF-3 convention, confirmed here).
  - The few non-control files in those two directories are accepted over-coverage and are enumerated in §3.
- `scripts/oversight/gates/`, `lib/` and `validators/` are wholly control-defining, so they get `**` globs.
- `bootstrap/`, `scripts/automation/` and the remainder of `scripts/` are listed per file.

---

## 3. Inventory

P = PROTECTED, U = UNPROTECTED. The rule column cites §2.

**Counts.**

| Area | Files | P | U |
|---|---|---|---|
| `bin/` | 9 | 8 | 1 (covered by `bin/**`, accepted) |
| `bootstrap/` | 29 | 19 | 10 |
| `scripts/framework/` | 70 | 65 | 5 (covered by `**`, accepted) |
| `scripts/automation/` | 33 | 22 | 11 |
| `scripts/oversight/` outside `gates/`, `validators/` | 35 | 27 | 8 |
| `scripts/oversight/gates/`, `validators/` | 12 + 24 | 36 | 0 |
| `scripts/` top level (13 `.sh` + `__init__.py`) and `scripts/dev/` | 15 | 5 | 10 |
| `.hos-manifest` (consumer runtime file) | 1 | 1 | 0 |

### 3.1 `bin/` — kept as `bin/**`

| File | | Rule | Reason |
|---|---|---|---|
| `hos-cron` | P | P1 | Cron launcher. It handles: the identity guard, suspend/halt/usage gate, baseline-halt, work selection and the prompt load. |
| `hos-human` | P | P1 | Human-proxy launcher and identity guard. |
| `hos-overseer` | P | P1 | Overseer launcher and identity guard. |
| `hos-worker` | P | P1 | Worker launcher and identity guard. |
| `hos-suspend` | P | P1 | Writes the suspend marker that `hos-cron` obeys (cron halt). |
| `hos-usage-poll` | P | P1 | Usage-pause poller (ADR-1944 AF-2). |
| `lib/usage_pause.py` | P | P1 | `evaluate_cycle`, the usage-pause decision. |
| `lib/git-credentials.sh` | P | P1/P2 | Credential helper. Sourced by `hos-cron`. |
| `hos-trim-logs` | U | N1 | Trims `/tmp` logs. Accepted over-coverage under `bin/**`. |

### 3.2 `bootstrap/` — per file (replaces `bootstrap/**`)

| File | | Rule | Reason |
|---|---|---|---|
| `apps.env.template` | P | P1 | Defines `BOT_ACCOUNTS` composition and the `OVERSEER_CEILING` default. Records why the Human App has no Administration. |
| `create_branch.sh` | P | P1 | Branch-ownership writer (ADR-037). |
| `get_app_token.sh` | P | P1 | Token minting and the identity login. |
| `hos_install.sh` | P | P1 | Installer. It handles: CORE/PACK merge and hard-stop, ship-set, CODEOWNERS/workflows install, `.hos-manifest`. |
| `hos_setup_partner.sh` | P | P1 | Writes `apps.env`: PEMs, bot logins, ceiling, human reviewer. |
| `invoke_agent.sh` | P | P1 | The single agent-invocation site (ADR-1643 AD-16). |
| `lib/branch_ownership.sh` | P | P1/P2 | Ownership record grammar. Sourced by `create_branch.sh`, `submit_pr.sh` and `hos-cron`. |
| `lib/comment_format_check.sh` | P | P2 | Sourced by `pr_review.sh`. |
| `lib/role_clone_check.sh` | P | P1/P2 | Role/clone identity cross-check. Sourced by the launchers. |
| `lib/sandbox_paths.sh` | P | P2 | Sourced by `hos_install.sh` for sandbox-policy generation. |
| `merge_authority.sh` | P | P1 | L3 wrapper for the merge-authority primitives (ADR-1357). |
| `overseer-cron-prompt.md` | P | P1 | Governance text: the overseer's autonomous loop. |
| `pr_review.sh` | P | P1 | Overseer verdict / reviewer-request wrapper (ADR-1657). |
| `query_issues.sh` | P | P4 | Named grant in `review-read-only-gh-read` (AF-3). |
| `revoke_app_token.sh` | P | P1 | Token lifecycle. |
| `submit_pr.sh` | P | P1 | Ownership refusal predicate, merge-from-base guard, and the `--app human --confirmed` gate. |
| `sync_apps_env.sh` | P | P1 | Appends identity/ceiling keys to `apps.env`. |
| `validate_setup.sh` | P | P1 | Launcher preflight and sandbox-policy currency check (ADR-1221 FR-9). |
| `worker-cron-prompt.md` | P | P1 | Governance text: the worker's autonomous loop. |
| `README.md` | U | N3 | Documentation. |
| `create_issue.sh` | U | N1 | Issue write. Decides nothing. |
| `edit_issue.sh` | U | N1 | Label, milestone, state and body write. The label-routing *policy* lives in protected agent text. |
| `edit_issue_edges.sh` | U | N1 | Edge write. The removal restriction lives in `CLAUDE.md`, and later in T3.3's check under `scripts/framework/`. |
| `escalate_to_human.sh` | U | N1 | Records an escalation that the *caller* decided. Record-first ordering is an integrity property, not a constraint on the bot. |
| `hos_bootstrap.sh` | U | N1/N3 | Machine provisioning. Human-run, and a release asset (the release is human-gated). Gates use the venv, not machine packages. |
| `hos_repo_sync.sh` | U | N1 | Fast-forward sync. `hos-human` runs it as `\|\| true`. |
| `post_comment.sh` | U | N1 | Comment write. Its format check is enforced through `lib/comment_format_check.sh` (protected). |
| `post_review_thread.sh` | U | N1 | Thread write. It can only *add* merge blockers. |
| `setup_clis.sh` | U | N1/N3 | Machine CLI install. Human-run. |

### 3.3 `scripts/framework/` — kept as `scripts/framework/**`

**P1:**
- `audit_predicate.py` — the audit-only exception to the overseer-approval gate.
- `check_agents_static.sh` — writes the phase-1 stamp; release phase 1.
- `check_validation_current.sh` — the validation-check gate.
- `consumer_agents.txt`, `framework_consumer_files.txt` — ship-sets. Dropping a gate from these disables it in consumers.
- `cut_release.sh` — release gate.
- `gen_codeowners.sh`, `regen_all.sh` — CODEOWNERS generation.
- `gen_sandbox_config.py` — sandbox policy.
- `install.sh` — installer / `config.sh` generator.
- `machine-accounts.env` — `BOT_ACCOUNTS`, ceiling.
- `protected_surfaces.txt` — this list.
- `provision_agent_account.sh` — identity configuration.
- `requester_trust.py`, `select_work_candidates.py` — intake trust (ADR-1540).
- `require_human_approval.py`, `require_overseer_approval.py`, `require_tier_ceiling.py`, `rerun_gate_checks.py` — server-side gates.
- `run_framework_validation.sh` — `cut_release` consumes its exit code.
- `run_tests.sh` — computes the required `tests` check.
- `run_tests_release.sh` — the release-required suite (`worker.md:646`).
- `setup_branch_protection.sh` — branch protection.
- `strip_internal_paths.sh` — rewrites CORE regions of shipped agents.

**P2:**
- `config.sh` — sourced by `check_agents_static.sh` and `run_second_review.sh`. It also substitutes values into agent text.

**P3:**
- `audit_allowlist.txt` — the predicate's allowlist.
- `decisions.md` — rule input to `validate_spec_compliance.sh`.
- `doc-patterns.md` — rule input to `validate_docs.sh`.
- `installer-internal-paths.txt` — which CORE lines are stripped from shipped agents.
- `placeholders.manifest` — substitutions into agent files.
- `run_tests_inner_loop.sh` — its exit code drives the `hos-cron` baseline halt.
- `scripts-review-ledger.jsonl` — finding-suppression ledger for `validate_scripts.sh`.
- `security_surfaces.txt` — `decide_merge_authority` input (#1253).
- `trusted-requesters.txt` — trust roster.
- `validate_agents.sh`, `validate_docs.sh`, `validate_scripts.sh`, `validate_self.sh`, `validate_spec_compliance.sh` — release-gate phases.
- `validation-stamps/phase1-*.stamp` (26 files) — evidence that `check_validation_current.sh` consumes.

**U (accepted over-coverage):**
- `gen_scripts_index.sh` — N3 (discovery index).
- `run_post_change_sweep.sh` — N3 (explain-only, executes no binding, HOS-only).
- `trusted-requesters.txt.example` — N3 ("never read by the gate").
- `validation-stamps/README.md`, `validation-stamps/.gitkeep` — N3.
- Measured cost of these five: 1 merge in 123.

### 3.4 `scripts/automation/` — per file (previously unprotected)

| File | | Rule | Reason |
|---|---|---|---|
| `__init__.py`, `lib/__init__.py` (and `scripts/__init__.py`) | P | P2 | Executed by every `scripts.automation.lib.*` import. |
| `agent_invoke_cli.py` | P | P1 | Invocation primitive: posture enforcement, fail-closed classification. |
| `dimension_registry_cli.py` | P | P1 | Sole CLI over the registry. Its plan is the required-review set (ADR-1643 W7). |
| `hos-coordination.defaults.yaml` | P | P3 | Layer-1 values for enable, thresholds and allowlist in `config_resolver`. |
| `merge_authority_cli.py` | P | P1 | L2 merge-authority primitives. |
| `pr_review_cli.py` | P | P1 | Decides the review event and the reviewer trigger. |
| `lib/breakers.py` | P | P1 | Failure cap and blast-radius caps (`worker.md`/`overseer.md` steps). |
| `lib/budget.py` | P | P1 | Budget gate. |
| `lib/claim.py` | P | P1 | Claim protocol. Rechecks activation and `hos-halt`. |
| `lib/config_resolver.py` | P | P1 | Narrow-only `enabled`/threshold/allowlist resolution. |
| `lib/correlation.py` | P | P2 | Imported by `claim.py` and `envelope.py`. |
| `lib/dimension_registry.py` | P | P1 | Registry loader. Integrity checks L27–L33. |
| `lib/envelope.py` | P | P1 | Requester-allowlist enforcement (GitHub-author check). |
| `lib/gate_compliance.py` | P | P1 | Gate non-override checks behind the evaluator's PROCEED. |
| `lib/github.py` | P | P2 | Imported by `merge_authority.py` and the CLIs. Supplies the reviews and checks they decide on. |
| `lib/ledger.py` | P | P2/P3 | Imported by `budget.py`, `breakers.py` and `probe.py`. The spend data source. |
| `lib/merge_authority.py` | P | P1 | `decide_merge_authority()`. |
| `lib/merge_config.py` | P | P1 | Resolves the machine-account keys for the matrix. |
| `lib/posture.py` | P | P1 | Posture validation V1–V14 (a security control). |
| `lib/probe.py` | P | P1 | Consumer-deployment authorization path (ADR-1540 A1). |
| `lib/triage.py` | P | P1 | Routes to `needs-human` or embargo (decides the escalation). |
| `dimension_sweep_cli.py` | U | N3 | "Observation only … gates nothing". |
| `fixtures/framing_patterns.jsonl` | U | N3 | Test data. Read only by `tests/`. |
| `pre_pr_stale_check.py`, `lib/stale_commit_detector.py` | U | N3 | Worker pre-push hygiene. Every predicate is re-derived downstream. |
| `lib/pr_readiness.py` | U | N3 | The worker's pre-PR *self*-check. CI, the overseer and the evaluator re-derive each condition it checks. Weakening it only lets PRs reach the binding checks. |
| `lib/cycle_log.py` | U | N1 | Audit event writer. `hos-cron` calls it as `\|\| true`. |
| `lib/self_review_source.py` | U | N1 | Files self-review findings. Trust is decided in `requester_trust.py` on the record, not the filer. |
| `lib/codeowners.py` | U | N2 | No production caller. Wiring it requires a product checkpoint (#559). |
| `lib/multi_customer.py`, `lib/observability.py`, `lib/overseer_state.py` | U | N2 | No production caller. |

### 3.5 `scripts/oversight/` outside `gates/` and `validators/`

`gates/**`, `lib/**` and `validators/**` are P in full.
- `gates/` (12 files): P1.
- `lib/` (`audit_log.py`, `audit_log.sh`, `changeset.sh`, `detect_stack.sh`, `git_depth.py`, `resolve_node_tool.sh`, `step_range.sh`, `vendor_invoke.sh`): each is sourced or imported by a P file (P2). `changeset.sh` is also P3 (it decides which files gates scan).
- `validators/` (24 files): P3. `run_validators.sh` turns their output into composite and tier, and `rn_calculator.py` is the server-side ceiling input.

| File | | Rule | Reason |
|---|---|---|---|
| `agents_static_logic.py` | P | P3 | Classification logic for the phase-1 stamp writer. |
| `change_classifier.py` | P | P1 | Forces `structural`, which sets the human-approval boundary (#75). |
| `changeset_logic.py` | P | P3 | Missing-path classifier for the gate file set. |
| `codeowners.py` | P | P1 | CODEOWNERS HUMAN_REQUIRED gate. Path-loaded by both CLIs. |
| `ensure_venv.sh` | P | P2 | Sourced by gates. Sets the interpreter and tool paths. |
| `panel_logic.py` | P | P3 | Panel floor rules and corroboration. Feeds the release-panel verdict. |
| `release_artifact_logic.py`, `release_logic.py` | P | P1 | Release-cut gate logic. |
| `release_panel_exclusions.txt`, `release_panel_logic.py` | P | P1/P3 | Release-panel verdict contract and exclusions (ADR-1340). |
| `requirements.txt` | P | P3 | Pins the tool versions that compute gate verdicts. |
| `run_gates.sh`, `run_validators.sh` | P | P1 | Gate and validator orchestration. |
| `run_with_retry.sh` | P | P2 | Sourced by gates. Owns the retry and exit path. |
| `second_review_logic.py`, `validation_logic.py` | P | P1 | Reviewer selection and verdict aggregation. |
| `secret_scan_logic.py` | P | P3 | Finding-level suppression for `secret_scan.sh`. |
| `signoff_gate.py` | P | P1 | Sign-off gate. |
| `suspension_manager.py` | P | P3 | Gate-suspension state, read inside `run_gates.sh`. |
| `audit_conditional_proceed.sh` | U | N3 | Read-only retroactive audit. |
| `check_pr_reviewed.sh` | U | N3 | Idempotency precheck. A wrong answer causes a skipped or duplicate review, never a merge. |
| `prompt_audit_logic.py` | U | N3 | Query tool for prompt artifacts. |
| `record_agent_model.py` | U | N1 | SubagentStop hook. Cannot block. |
| `retry_rescue_logic.py` | U | N3 | Flaky-test observability. Does not change the pytest outcome. |
| `sign_off.sh` | U | N3 | Stamp writer. `signoff_gate.py` verifies the stamps. |
| `smoke_test.sh` | U | N3 | Read-only health check. |
| `token_tracker.py` | U | N1 | Usage record. Called as a fire-and-forget subprocess. |

### 3.6 `scripts/` top level, `scripts/dev/`

- **P (P1):**
  - `run_second_review.sh` — second-review entry point. **Closes TD-1643 Amendment E §E.10 Q2(a).**
  - `run_review_chain.sh` — resolves the tier and decides whether second review runs (`worker.md:379`).
  - `run_panel.sh` — panel engine, including the release-panel verdict path.
  - `run_release_panel.sh` — release gate (ADR-1340).
- **P (P2):** `scripts/__init__.py`.
- **U:**
  - `branch_clean.sh` — N1.
  - `capture_prompt.sh`, `capture_session.sh`, `prompt_audit.sh` — N3 (artifact tools).
  - `migrate_audit_log_to_dir.sh` — N2 (throwaway).
  - `review_self.sh`, `reverify_self.sh` — N3 (advisory self-review).
  - `run_red_team.sh` — N3 (a human reads its output; nothing consumes its exit code).
  - `run_redteam_sample.sh` — N3 (research sampling).
  - `dev/commit_onto_base.sh` — N1.

### 3.7 `.hos-manifest` — PROTECTED (closes Amendment E §E.10 Q2(b))

- L31 fails closed on a manifest mismatch. A hash anchor must be at least as protected as `core.yaml` (under `contract/**`), the file it anchors.
- The only legitimate writer, `hos_install.sh`, writes `.hos-release` in the same change, and `.hos-release` is already protected. Protecting the manifest therefore adds no human gate.
- With this ruling, L31 becomes a tamper control as well as an integrity control, against bot edits. It is not a control against local edits that never reach a PR.

---

## 4. New `scripts/framework/protected_surfaces.txt` (complete file)

```
# Canonical protected-surface globs (single source of truth) — AGENT-IDENTITY.md §9.
#
# Any PR whose diff touches one of these requires a HUMAN approval, regardless of
# computed risk tier — no bot (worker or overseer) may approve or merge it. These
# are the surfaces that DEFINE the controls; they can never be loosened on the
# controls' own say-so.
#
# Classification rule (ADR-1935 §2): a path is listed iff it DEFINES or ENFORCES a
# control (P1), is an in-process dependency of a listed file (P2: Python import,
# package __init__, importlib path load, shell `source`), is a subprocess or data
# file whose output a listed file consumes as a decision input (P3), or is named
# individually in an allow rule of a restrictive review posture (P4). Transport-
# only wrappers are deliberately NOT listed. Classify a new file by ADR-1935 §2,
# not by its directory.
#
# Consumed by:
#   - scripts/framework/require_human_approval.py  (the server-side status check)
#   - scripts/framework/gen_codeowners.sh          (generates .github/CODEOWNERS)
#   - scripts/automation/lib/merge_authority.py    (touches_protected_surface)
# Keep this list, AGENT-IDENTITY.md §9, and the generated CODEOWNERS in sync.
#
# Glob syntax: `dir/**` = that directory and everything under it; `*` = one path
# segment; a plain path = that exact file. Blank lines and `#` comments ignored.

# Agent definitions and governance text.
.claude/agents/**
contract/**
AGENTS.md
CLAUDE.md
templates/CLAUDE.human.md
docs/AGENTS.md
docs/AGENT-IDENTITY.md
METHODOLOGY.md
docs/FABERIX-ROLES.md
docs/CROSS-REPO-CONDUCT.md

# Whole-directory control homes (ADR-1935 §2). Every launcher in bin/ is a cron,
# identity or usage-pause control; scripts/framework/ is where controls are placed
# so that they are protected by construction (ADR-1540 AF-3, ADR-035, ADR-1221).
bin/**
scripts/framework/**

# bootstrap/ — per file (ADR-1935 §3.2). Credential/identity, branch ownership,
# merge-authority and review-verdict wrappers, agent invocation, the installer,
# the one wrapper a restrictive review posture grants by name (query_issues.sh,
# rule P4), and the cron prompts. The other issue/comment/label/edge wrappers
# and the machine-bootstrap scripts are deliberately NOT listed.
bootstrap/apps.env.template
bootstrap/create_branch.sh
bootstrap/get_app_token.sh
bootstrap/hos_install.sh
bootstrap/hos_setup_partner.sh
bootstrap/invoke_agent.sh
bootstrap/lib/branch_ownership.sh
bootstrap/lib/comment_format_check.sh
bootstrap/lib/role_clone_check.sh
bootstrap/lib/sandbox_paths.sh
bootstrap/merge_authority.sh
bootstrap/overseer-cron-prompt.md
bootstrap/pr_review.sh
bootstrap/query_issues.sh
bootstrap/revoke_app_token.sh
bootstrap/submit_pr.sh
bootstrap/sync_apps_env.sh
bootstrap/validate_setup.sh
bootstrap/worker-cron-prompt.md

# Python package initialisers — executed in-process by every protected
# `scripts.*` import below (ADR-1935 §2, rule P2).
scripts/__init__.py
scripts/automation/__init__.py
scripts/automation/lib/__init__.py

# Merge authority, review verdicts, agent invocation, work-loop controls (#1935).
scripts/automation/agent_invoke_cli.py
scripts/automation/dimension_registry_cli.py
scripts/automation/hos-coordination.defaults.yaml
scripts/automation/merge_authority_cli.py
scripts/automation/pr_review_cli.py
scripts/automation/lib/breakers.py
scripts/automation/lib/budget.py
scripts/automation/lib/claim.py
scripts/automation/lib/config_resolver.py
scripts/automation/lib/correlation.py
scripts/automation/lib/dimension_registry.py
scripts/automation/lib/envelope.py
scripts/automation/lib/gate_compliance.py
scripts/automation/lib/github.py
scripts/automation/lib/ledger.py
scripts/automation/lib/merge_authority.py
scripts/automation/lib/merge_config.py
scripts/automation/lib/posture.py
scripts/automation/lib/probe.py
scripts/automation/lib/triage.py

# Gate and validator outcome computation, and everything a gate sources.
scripts/oversight/gates/**
scripts/oversight/lib/**
scripts/oversight/agents_static_logic.py
scripts/oversight/change_classifier.py
scripts/oversight/changeset_logic.py
scripts/oversight/codeowners.py
scripts/oversight/ensure_venv.sh
scripts/oversight/panel_logic.py
scripts/oversight/requirements.txt
scripts/oversight/run_gates.sh
scripts/oversight/run_validators.sh
scripts/oversight/run_with_retry.sh
scripts/oversight/second_review_logic.py
scripts/oversight/secret_scan_logic.py
scripts/oversight/signoff_gate.py
scripts/oversight/suspension_manager.py
scripts/oversight/validation_logic.py
scripts/oversight/validators/**

# Release gating (ADR-1340) — the release-cut and release-panel verdict path.
scripts/oversight/release_artifact_logic.py
scripts/oversight/release_logic.py
scripts/oversight/release_panel_exclusions.txt
scripts/oversight/release_panel_logic.py

# Review pipeline entry points (closes TD-1643 Amendment E §E.10 Q2(a)).
scripts/run_panel.sh
scripts/run_release_panel.sh
scripts/run_review_chain.sh
scripts/run_second_review.sh

.github/CODEOWNERS
.github/workflows/**

# Unattended-worker governance surfaces (#254). These decide whether the
# autonomous worker may run, how much it may spend, and whose commands it obeys —
# the highest control-loosening surfaces of all. A bot must never self-authorize
# by merging a change to its own enable/budget/allowlist or to the kill switch.
PROJECT/hos-coordination.yaml
PROJECT/hos-halt

# Release artifacts (#761). Releases are always human-approved (NG3b).
# Adding these as a server-side protected-surface guard backs up the behavioral
# NG3b rule in overseer.md so that even if the title/content heuristic misses,
# the protected-surface gate enforces HUMAN_REQUIRED.
docs/releases/**
.hos-release
# The L31 integrity anchor (TD-1643 Amendment E §E.10 Q2(b), ADR-1935 §3.7). Its
# only legitimate writer (hos_install.sh) also writes .hos-release, so this adds
# no human gate.
.hos-manifest
```

**Net effect:**
- Protected tracked files go from 208 to 274 (excluding `audit/`).
- 76 files become newly protected.
- 10 files are no longer protected, all in `bootstrap/` (§3.2's U rows).
- Every glob matches at least one tracked file, except the four runtime/consumer files (`PROJECT/hos-coordination.yaml`, `PROJECT/hos-halt`, `.hos-release`, `.hos-manifest`).

---

## 5. Ripple analysis

### 5.1 Must change in the implementing PR

1. **`scripts/framework/protected_surfaces.txt`**: replace with §4.
2. **`.github/CODEOWNERS`**: regenerate with `bash scripts/framework/regen_all.sh`. Do not edit it by hand. This makes `test_codeowners_current.py` and `test_regen_all.py` pass again.
3. **`tests/automation/test_dimension_registry_data.py` T5.63**:
   - The ratchet fires as designed. Change the last assertion to `assert set(tools) - protected == set()`.
   - Rename the test to `test_t5_63_every_core_tool_is_protected` and delete the "Ratchet … #1935" comment.
   - **Do not** weaken this to `<=` or delete it (TD-D42).
4. **`tests/framework/test_require_human_approval.py::test_near_misses_do_not_match`**:
   - Remove `validators/rn_calculator.py` and `scripts/run_second_review.sh`.
   - Add the now-correct near-misses `bootstrap/edit_issue.sh`, `bootstrap/post_comment.sh`, `scripts/run_red_team.sh`, `scripts/automation/lib/cycle_log.py` and `scripts/oversight/token_tracker.py`.
5. **New `tests/framework/test_protected_surface_classification.py`**:
   - **T-1935-1 (closure).** Covers every PROTECTED executable file: `.py`, `.sh`, and extensionless shebang files under `bin/`; *not* `.md`.
     - Every repo-resolvable dependency must itself match the list or appear in `scripts/framework/protected_closure_exemptions.txt` (see the next item). Dependencies are:
       - `scripts.*` dotted imports;
       - package `__init__.py` files on the import path;
       - literal `*.py`/`*.sh` path strings;
       - `source`/`.` targets.
     - Dynamic targets (e.g. `source "$TOKEN_FILE"`) are listed in the exemptions file as `dynamic`.
     - This is the mechanical form of P2/P3. A new trusted dependency cannot land unprotected, because the PR that wires it in touches a protected file. A human therefore sees the failure, or the exemption.
   - **T-1935-2 (status pins).** Parametrized `matched_surfaces` assertions, one per rule and directory. Include at least:
     - P: `bootstrap/query_issues.sh`, `scripts/automation/lib/github.py`, `scripts/oversight/lib/changeset.sh`, `scripts/oversight/validators/rn_calculator.py`, `scripts/run_second_review.sh`, `scripts/__init__.py`, `.hos-manifest`.
     - U: every §3.2 U row.
   - **T-1935-3 (no dead globs).** Each glob must match at least one tracked file, except an explicit set holding the four runtime/consumer files. A typo must not silently protect nothing.
6. **New `scripts/framework/protected_closure_exemptions.txt`**:
   - One line per exempt dependency: `<path> <N1|N2|N3|dynamic> <reason>`.
   - It is protected by `scripts/framework/**`, so a bot cannot widen it.
   - Seed it from §3's N rows that a protected file references (e.g. `cycle_log.py`, `token_tracker.py`, `hos_repo_sync.sh`).
   - `technical-design` owns the extraction heuristic. It may tune extraction but may not drop T-1935-1.
7. **`docs/AGENT-IDENTITY.md` §9.0 (sync)**:
   - Replace the glob code block and its parenthetical with: the P1 category list; P2–P4 in one sentence each; the two directory homes; and "the enumerated list is `scripts/framework/protected_surfaces.txt` (classified per ADR-1935 §2)".
   - Keep the `CLAUDE.md` rationale sentence.
   - Duplicating paths here is what let the doc and the file drift.
8. **`docs/GATE-COVERAGE-MECE.md:80`**: the sentence claims `scripts/oversight/**` is protected, which was never true. Replace it with "`scripts/oversight/requirements.txt` (gate tool versions) and `.github/workflows/**` require human approval".
9. **`DECISIONS.md`**: append one entry. It records: the rule, the measured rates (AF-1), the AF-3 correction, and the ADR-1542 obligation in §5.2.
10. **Implementing-PR description**:
    - The §8 affected-approvals table.
    - Avoid the literal "closes #N" phrasing for any issue other than #1935 (#1856 hazard).

### 5.2 Guarantees other ADRs rely on

| Source | Guarantee | Status under §4 |
|---|---|---|
| ADR-1540 AF-3, Amendments 2–5; ADR-1644 (stage module in `scripts/framework/`) | Trust gate, roster and selection are protected by placement | **Holds**: `scripts/framework/**` kept. `bin/hos-cron`, `worker-cron-prompt.md` and `.github/workflows/**` listed. |
| ADR-035 / ADR-036 | Predicate, allowlist and `require_overseer_approval.py` are protected. `scripts/automation/**` is *not*, so Component H is ungated | **Holds**. `pre_pr_stale_check.py` stays U, consistent with ADR-035:186. |
| ADR-038, ADR-1221 | Launchers, token minter and declaration file (`scripts/framework/`) protected. `gen_sandbox_config.py`, `validate_setup.sh` (FR-9 hook) and `sandbox_paths.sh` protected | **Holds**: all listed. |
| ADR-1944 AF-2 | All usage-pause decision code is on a protected surface | **Holds**: `bin/**` kept. |
| ADR-1357 / ADR-1657 | `merge_authority.sh` and `pr_review.sh` are protected | **Holds**, and is **strengthened**: their L2 CLIs and L1 libraries are now protected too. |
| ADR-1643 AD-16, Amendment 5 | `invoke_agent.sh` is protected. `query_issues.sh`'s argument handling is a "human-gated" permission boundary | **Holds**: AD-16 by P1, Amendment 5 by P4 (AF-3). |
| ADR-1643 Amendment E (TD-D42, TD-D48) | T5.63 ratchet. L31 is integrity, not tamper | **Resolved**: ratchet updated to `set()`. `.hos-manifest` protected (§3.7). |
| `merge_authority.py:446`, DECISIONS #1253, `audit_allowlist.txt:12` | `security_surfaces.txt` / `audit_allowlist.txt` are protected via `scripts/framework/**` | **Holds**. |
| ADR-1340 | Release-panel exclusions follow the protected-list precedent | **Holds**, and is **strengthened**: now actually protected. |
| **ADR-1542 Q4** | "Adding a named operation is a `bootstrap/**` PR, which is CODEOWNERS-gated" | **Would be removed. Re-anchored, binding:** a wrapper's capability reaches a restrictive session only through a posture or role-template allow rule. Those rules live in `contract/**` (protected), and P4 then protects the named wrapper. **Obligation on ADR-1542 slice 9 (FR-8 role templates): grant each wrapper by exact path. A wildcard over `bootstrap/` is forbidden**, because it would void Q4. Q4's "no caller-supplied URL/endpoint/jq/GraphQL" corollary is unchanged and stays a `security-reviewer` obligation. |
| TD-1644 T3.0a/T3.3a file tables ("protected") for `escalate_to_human.sh`, `edit_issue*.sh` | Descriptive status only. No mechanism depends on it (edge-removal policy: `CLAUDE.md`; future T3.3 check: `scripts/framework/`) | **Superseded** for those three files. No guarantee is lost. |

### 5.3 Historical documents left as they are

These record the list as it was when they were written. Do not edit them:
- ADR-035, ADR-036, ADR-038, ADR-1221, ADR-1357, ADR-1415, ADR-1540 and its amendments, ADR-1542, ADR-1657, ADR-1944.
- TD-1643 (including the `protected_surfaces.txt:21/:29` line citations, which go stale when the file is renumbered), TD-1644 T3.0a/T3.0b/T3.3a, TD-1542 S1, TD-1759.
- `docs/specs/UNATTENDED-WORKER-PROTOCOL.md:407`, `research/**`.

No change is needed in these, because they read the file rather than copying it:
- `.claude/agents/overseer.md`
- `CLAUDE.md` ("`.claude/agents/**` is its first entry" stays true)
- `docs/MACHINE-ACCOUNTS-SETUP.md`, `docs/GENERATED-ARTIFACTS.md`
- `docs/AGENTS.md:917`, `OVERSIGHT-RUNBOOK.md:864`, `post-change-sweep.md:46` (review-routing categories, not protection)

The sandbox policy is independent of this list (`denyWrite` holds only `bin` and the values sidecar) and does not change.

**Open PRs at merge time.** CODEOWNERS is evaluated from the base branch, so any open PR that touches a newly protected file needs a code-owner approval as soon as this merges. The overseer's `touches_protected_surface` also re-reads the list every cycle. A stale green `require-human-approval` run on such a PR therefore cannot carry it to merge.

---

## 6. Residuals (accepted, stated)

- **R-1 — Code execution.** Repo code that Worker/Overseer executes already has every App PEM (AF-4). The containment for this lies elsewhere: the sandbox/permission posture (#1146, ADR-1542 ESC-2) and the base-checkout `pull_request_target` gates.
- **R-2 — Shared-namespace controls are not listed** (AF-7): `pyproject.toml` (flake8 and `fail_under`), `tests/conftest.py` (in-process pytest hooks for the required `tests` check), `.claude/settings.json` (allow list and SubagentStop hook) and `.claude/commands/**` (merge-decision prompt text).
  - By §2 they are controls in HOS.
  - Listing them in the shipped file would gate consumers' own files.
  - **Recommended follow-up:** a HOS-only, non-shipped extension list read by both list consumers. Shipping that is a separate issue.
- **R-3 — Tests and evidence are unprotected:** `tests/**` (apart from R-2), `signoffs/**`, `audit/**`. Protected checks re-verify the evidence. Weakening a test is a visible diff that the overseer reviews.
- **R-4 — Accepted over-coverage:** `bin/hos-trim-logs`, the five §3.3 U files, and `validators/brownfield.py` (not wired in yet).
- **R-5 — Pre-existing, not #1935's.** `review-read-only-gh-read` ships to consumers, but `bootstrap/query_issues.sh` is not in the consumer ship-set (ADR-1357 AF-5). The orchestrator should file this separately.

---

## 7. Escalations

**ESC-1 (human + pm-agent): clear the operational-burden increase before the list binds.**
- Measured on 123 merges, the share of PRs needing a human goes from **43% to 49%** (server-side: 37% to 48%). The issue expected a decrease, and AF-1 shows that no correct classification produces one.
- The added gates fall on second-review verdict code, agent posture, the review registry, gate file-set and suspension code, the release panel and the merge-authority CLIs. Each of these is a control the bots are currently able to approve for themselves.
- Consumer impact is negligible: consumers rarely edit HOS-owned files, and upgrade PRs are already human-gated through `.hos-release`.
- **Options:**
  - **(a) Accept §4 as ruled.** *Recommended.*
  - **(b) Accept §4 minus `scripts/automation/**` and the second-review set**, re-filed as a follow-up. *Not recommended:* it leaves the code that computes approve verdicts mergeable on bot approval.
  - **(c) Reject the increase and pursue load relief only through #1936.** This leaves AF-2 open.
- **If not cleared:** the implementing PR may still be built and reviewed, but it may not merge.

There are no other escalations. Every remaining classification is decided above.

---

## 8. Startup-gap and affected sign-offs

- **Startup-gap.** This is a `startup-artifact-gap`.
  - AGENT-IDENTITY §9.0 already said in prose that "a gate/validator" and the "identity/authority model" are protected.
  - The v0.2.0 glob list never implemented that sentence: validators other than `schema.py`, second review, `scripts/automation/` and the gate libraries were all left out.
  - **Action for the orchestrating session** (this ADR posts nothing): annotate #1935 with the `startup-artifact-gap` label/annotation.
- **Affected sign-offs.**
  - Prior approvals of the 76 newly protected files **stand as approvals of behavior**. They were valid under the rules in force.
  - However, the code now on `main` for those files may never have had a human approve it, and that leaves it unaudited against the corrected requirement.
  - **Obligation (no new gate):**
    - The implementing PR's description carries a table with one row per newly protected file. Each row gives the last merge that modified the file and whether that merge had a human approval (from `merge_authority.sh human-approval`).
    - The human approving the implementing PR reviews that table. They decide whether any file needs a dedicated re-review issue.
  - Approvals of the 10 no-longer-protected `bootstrap/` files are unaffected.
