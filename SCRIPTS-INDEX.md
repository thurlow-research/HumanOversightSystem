# SCRIPTS-INDEX.md

GENERATED — do not edit by hand. Run `scripts/framework/gen_scripts_index.sh`
to regenerate.

A script's absence from this index means **verify it doesn't exist**
(search `scripts/`, `bootstrap/`, `bin/`), not that it doesn't exist —
this index can lag; regenerate with `scripts/framework/gen_scripts_index.sh`
if in doubt.

Scope: `bin/` (top-level), `bootstrap/` (top-level), `scripts/` (recursive,
including `scripts/automation/lib/*.py`). Test files, `__pycache__`, and
non-executable data files (`.txt`, `.jq`, `.md`, `.env*`, `.template`) are
excluded.

## bin/

- `bin/hos-cron` — parameterized HOS cron launcher
- `bin/hos-human` — interactive HOS human-proxy session launcher
- `bin/hos-overseer` — interactive HOS overseer session launcher
- `bin/hos-suspend` — pause/resume a HOS project cron cycle without touching the crontab
- `bin/hos-trim-logs` — trim HOS cron agent logs to prevent unbounded growth
- `bin/hos-worker` — interactive HOS worker session launcher

## bootstrap/

- `bootstrap/create_branch.sh` — the single sanctioned branch-creation seam for the autonomous worker (#967, ADR-037, SPEC-967 R1)
- `bootstrap/create_issue.sh` — canonical wrapper for creating a GitHub issue under a HOS bot identity (#1085)
- `bootstrap/edit_issue.sh` — canonical wrapper for editing an existing GitHub issue or PR's metadata under a HOS bot identity (#1175, consolidated by #1204)
- `bootstrap/get_app_token.sh` — generate a GitHub App installation token for HOS bot identities
- `bootstrap/hos_bootstrap.sh` — Human Oversight System — MACHINE bootstrap.
- `bootstrap/hos_install.sh` — Human Oversight System — PROJECT installer.
- `bootstrap/hos_repo_sync.sh` — fetch + fast-forward the current repo's default branch, but only if enough time has passed since the last sync.
- `bootstrap/hos_setup_partner.sh` — guided per-project HOS credential setup
- `bootstrap/post_comment.sh` — canonical wrapper for posting a GitHub issue/PR comment under a HOS bot identity (#1155)
- `bootstrap/post_review_thread.sh` — canonical wrapper for posting a resolvable PR review thread under a HOS bot identity (#1207)
- `bootstrap/query_issues.sh` — canonical read-side wrapper for GitHub issue and PR queries under a HOS bot identity (#1192, consolidated by #1204)
- `bootstrap/revoke_app_token.sh` — revoke the GitHub App installation token currently held in GH_TOKEN (#1191)
- `bootstrap/setup_clis.sh` — Repo-independent machine bootstrap for the AI-oversight agent CLIs.
- `bootstrap/submit_pr.sh` — canonical wrapper for pushing a branch and opening a PR under a HOS bot identity (#1085)
- `bootstrap/sync_apps_env.sh` — fill gaps in an EXISTING .config/hos/apps.env
- `bootstrap/validate_setup.sh` — HOS preflight check

## scripts/

- `scripts/branch_clean.sh` — reset the Human clone to a clean, synced main
- `scripts/capture_prompt.sh` — scaffold a prompt artifact in the prompts/ directory
- `scripts/capture_session.sh` — session turn log, summary, and watermark management.
- `scripts/migrate_audit_log_to_dir.sh` — THROWAWAY one-time migration (#888 P4 / TD-888 §7).
- `scripts/prompt_audit.sh` — query the prompt artifact audit trail
- `scripts/reverify_self.sh` — send agy a targeted re-review of the fixes made in response to its initial self-review findings.
- `scripts/review_self.sh` — run an external reviewer (agy or codex) against the HOS itself.
- `scripts/run_panel.sh` — the local cross-vendor multi-agent review panel (Layer 2).
- `scripts/run_redteam_sample.sh` — statistical sampling red-team for LOW-tier escaped-defect rate.
- `scripts/run_red_team.sh` — system-level adversarial red-team at build milestones.
- `scripts/run_review_chain.sh` — orchestrate the full HOS oversight pipeline in tier-gated order.
- `scripts/run_second_review.sh` — pre-PR cross-vendor second code review.

## scripts/automation/

- `scripts/automation/pre_pr_stale_check.py` — CLI wrapper for the pre-PR stale-commit guard (#850).

## scripts/automation/lib/

- `scripts/automation/lib/breakers.py` — Circuit breakers and safety nets for the HOS automation loop (T13, §11).
- `scripts/automation/lib/budget.py` — Per-task token estimation and per-window budget gate for the HOS automation loop.
- `scripts/automation/lib/claim.py` — Claim-then-verify with UUIDv4 instance-id and heartbeat (T8, §7, ADR-2 backstop).
- `scripts/automation/lib/codeowners.py` — CODEOWNERS parser and actor-authorization signal (O19, §13).
- `scripts/automation/lib/config_resolver.py` — 4-layer config resolver for the HOS automation loop (T2, R13.1–R13.3).
- `scripts/automation/lib/correlation.py` — Correlation-id derivation, artifact naming, idempotency precheck, and cold-start recovery state machine for the HOS automation loop.
- `scripts/automation/lib/cycle_log.py` — write structured cycle events as per-entry audit records.
- `scripts/automation/lib/envelope.py` — Machine-readable HOS coordination envelope — parse, emit, threading, idempotency.
- `scripts/automation/lib/gate_compliance.py` — deterministic gate non-override invariant helpers (SPEC-375).
- `scripts/automation/lib/github.py` — Shared GitHub REST-by-id wrapper for the HOS automation loop.
- `scripts/automation/lib/ledger.py` — Append-only per-run cost/action ledger for the HOS automation loop.
- `scripts/automation/lib/merge_authority.py` — Merge-authority detection, matrix, queue, and guard rails (T10, §9, O3).
- `scripts/automation/lib/multi_customer.py` — Multi-customer fairness wiring (B14, R12.1–R12.3, O15).
- `scripts/automation/lib/observability.py` — Observability — JSONL-first run ledger consumers and derived Markdown log (T14, R11.8).
- `scripts/automation/lib/overseer_state.py` — Deterministic state helpers for the HOS oversight loop.
- `scripts/automation/lib/probe.py` — Token-free "is there work?" probe across customer repos (T4, §10, R10.1b).
- `scripts/automation/lib/pr_readiness.py` — worker pre-PR deterministic self-assessment gate (#317, #1131).
- `scripts/automation/lib/self_review_source.py` — Scheduled self-review work source (T12, §3.2, O6, O9).
- `scripts/automation/lib/stale_commit_detector.py` — Pre-PR stale-commit guard (#850).
- `scripts/automation/lib/triage.py` — Issue triage for the HOS automation loop (T6, §5).

## scripts/dev/

- `scripts/dev/commit_onto_base.sh` — commit files onto a base ref without a checkout

## scripts/framework/

- `scripts/framework/check_agents_static.sh` — fast static consistency checker for the agent pipeline.
- `scripts/framework/check_validation_current.sh` — verify that agent content has a valid validation stamp.
- `scripts/framework/config.sh` — HumanOversightSystem framework source configuration.
- `scripts/framework/cut_release.sh` — cut a validated HOS release.
- `scripts/framework/gen_codeowners.sh` — generate .github/CODEOWNERS from the canonical protected surface list (scripts/framework/protected_surfaces.txt), so CODEOWNERS and the require_human_approval status check can never drift (AGENT-IDENTITY.md §9).
- `scripts/framework/gen_sandbox_config.py` — generate or check a clone's sandbox policy (#1221).
- `scripts/framework/gen_scripts_index.sh` — generate SCRIPTS-INDEX.md, a directory-grouped index of every script and library module under bin/ (top-level), bootstrap/ (top-level), and scripts/ (recursive, including scripts/automation/lib/*.py), with a one-line description pulled from each file's header comment (.sh) or module docstring (.py).
- `scripts/framework/install.sh` — install or update the agent pipeline framework in a project repo.
- `scripts/framework/provision_agent_account.sh` — Configure a checkout to operate as an HOS machine account.
- `scripts/framework/require_human_approval.py` — server-side §9 protected-surface gate.
- `scripts/framework/require_overseer_approval.py` — server-side overseer-review gate.
- `scripts/framework/require_tier_ceiling.py` — server-side overseer ceiling gate.
- `scripts/framework/rerun_gate_checks.py` — review-triggered re-evaluation of the server-side gates.
- `scripts/framework/run_framework_validation.sh` — run the full framework validation suite.
- `scripts/framework/run_post_change_sweep.sh` — shell entrypoint for the post-change sweep.
- `scripts/framework/run_tests_inner_loop.sh` — Run the inner-loop test suite (required for PR approval).
- `scripts/framework/run_tests_release.sh` — Run the full test suite (required for release).
- `scripts/framework/run_tests.sh` — run unit tests and optionally mutation tests for HOS validators.
- `scripts/framework/setup_branch_protection.sh` — Apply HOS §9 branch protection rules via gh api.
- `scripts/framework/strip_internal_paths.sh` — strip HOS-internal-path lines from CORE regions of agent files before they are shipped to consumers.
- `scripts/framework/validate_agents.sh` — AI-powered cross-vendor review of agent definitions and docs.
- `scripts/framework/validate_docs.sh` — AI-powered documentation coverage validator.
- `scripts/framework/validate_scripts.sh` — review the framework's SCRIPTS (not just its agents/docs).
- `scripts/framework/validate_self.sh` — Opus self-review of the framework.
- `scripts/framework/validate_spec_compliance.sh` — checks that the agent pipeline implementation satisfies the governance requirements defined in METHODOLOGY.md, AGENTS.md, and decisions.md.

## scripts/oversight/

- `scripts/oversight/agents_static_logic.py` — pure classification logic for check_agents_static.sh.
- `scripts/oversight/audit_conditional_proceed.sh` — retroactive audit of CONDITIONAL_PROCEED PRs (#370).
- `scripts/oversight/change_classifier.py` — deterministic, independent classification of a diff.
- `scripts/oversight/codeowners.py` — CODEOWNERS-derived HUMAN_REQUIRED gate (SPEC-303b).
- `scripts/oversight/ensure_venv.sh` — Create the oversight pip venv if it does not exist.
- `scripts/oversight/panel_logic.py` — corroboration counting and tier ranking for the review panel.
- `scripts/oversight/prompt_audit_logic.py` — pure logic for the prompt-artifact audit tool.
- `scripts/oversight/record_agent_model.py` — record the resolved model ID for a subagent invocation into the audit trail (#1122 Option C, revised acceptance criterion 3).
- `scripts/oversight/release_artifact_logic.py` — release-gate deep artifact validation (#695).
- `scripts/oversight/release_logic.py` — semver bump, authored-notes gate, asset verification.
- `scripts/oversight/run_gates.sh` — central gate runner (SPEC-375 / REQ-GATE-NN-16).
- `scripts/oversight/run_validators.sh` — orchestrate all risk assessment validators for a file set.
- `scripts/oversight/run_with_retry.sh` — shared timeout + retry wrapper for validators and gates.
- `scripts/oversight/second_review_logic.py` — reviewer selection + verdict aggregation for second review.
- `scripts/oversight/signoff_gate.py` — validation-suite sign-off gate (HOS framework script).
- `scripts/oversight/sign_off.sh` — write a validation-suite sign-off stamp.
- `scripts/oversight/smoke_test.sh` — one-shot health check for every dependency a HOS session relies on: agent CLIs, oversight venv scanners, the IP/provenance scanner, and the validator orchestrator.
- `scripts/oversight/suspension_manager.py` — manage contract/gate-suspension.md.
- `scripts/oversight/token_tracker.py` — track and report external CLI token usage across oversight runs.
- `scripts/oversight/validation_logic.py` — dedup fingerprinting + verdict aggregation for the cross-vendor validation scripts (SPEC-334 / Issue #334).

## scripts/oversight/gates/

- `scripts/oversight/gates/astro_check.sh` — Astro project sanity gate (blocking on errors).
- `scripts/oversight/gates/bash_check.sh` — shell-portability invariant gate (blocking).
- `scripts/oversight/gates/check_suspension.sh` — shared helper for gate suspension checks.
- `scripts/oversight/gates/collection_integrity.sh` — test-suite collection-integrity gate (blocking on errors).
- `scripts/oversight/gates/django_check.sh` — Django system check gate (blocking on errors).
- `scripts/oversight/gates/expensive_gates_stub.sh` — placeholder + static container-start check.
- `scripts/oversight/gates/lint_check.sh` — style and formatting gate (blocking).
- `scripts/oversight/gates/portability_check.sh` — flag machine-specific absolute paths in source (blocking).
- `scripts/oversight/gates/secret_scan.sh` — hardcoded secret detection gate (blocking).
- `scripts/oversight/gates/security_scan.sh` — security static analysis gate (blocking on HIGH).
- `scripts/oversight/gates/template_refs_check.sh` — Django template-reference existence gate (blocking).
- `scripts/oversight/gates/type_check.sh` — static type checking gate (blocking).

## scripts/oversight/lib/

- `scripts/oversight/lib/audit_log.py` — canonical per-entry audit-record helper (SPEC-888 / TD-888 P1).
- `scripts/oversight/lib/audit_log.sh` — Bash facade over the canonical Python audit-record helper. (SPEC-888 / TD-888 §2.2, P1)
- `scripts/oversight/lib/detect_stack.sh` — repo-marker tool detection + fail-hard preflight (D1, ADR-032).
- `scripts/oversight/lib/resolve_node_tool.sh` — discover-only consumer JS toolchain resolver (D2, ADR-032).
- `scripts/oversight/lib/step_range.sh` — shared step commit-range helper (SPEC-220 BC-220-5).

## scripts/oversight/validators/

- `scripts/oversight/validators/brownfield.py` — brownfield classification for HOS layered-agent migration (#275).
- `scripts/oversight/validators/complexity_metrics_js.py` — cyclomatic complexity for JS/TS via tree-sitter.
- `scripts/oversight/validators/complexity_metrics.py` — cyclomatic complexity via radon.
- `scripts/oversight/validators/diff_size.py` — Diff-size risk-tier floor and multi-purpose split trigger (#377).
- `scripts/oversight/validators/function_metrics_js.py` — function-level size/structure metrics for JS/TS via tree-sitter (S5, ADR-032 D5).
- `scripts/oversight/validators/function_metrics.py` — function-level size and structure metrics via AST.
- `scripts/oversight/validators/hallucination_surface_js.py` — npm-ecosystem version-sensitive API detection + package.json dependency-existence check (S7, ADR-032, epic #1029).
- `scripts/oversight/validators/hallucination_surface.py` — version-sensitive API usage detection.
- `scripts/oversight/validators/ip_check.py` — IP/provenance validator for the Human Oversight System.
- `scripts/oversight/validators/issue_query.py` — historical bug density from GitHub issues and git churn.
- `scripts/oversight/validators/migration_scorer.py` — Django migration risk classification.
- `scripts/oversight/validators/n1_detector_js.py` — JS/TS N+1 analog via tree-sitter (S9, ADR-032 D8).
- `scripts/oversight/validators/n1_detector.py` — Django N+1 query heuristic via AST pattern matching.
- `scripts/oversight/validators/portability_check.py` — detect portability defects that prevent code from running on any host other than the developer's own machine.
- `scripts/oversight/validators/prompt_audit_risk.py` — Prompt provenance and ambiguity risk validator.
- `scripts/oversight/validators/regions.py` — the byte-exact region mechanism for HOS layered agent files.
- `scripts/oversight/validators/rn_calculator_js.py` — Dai et al. (2024) Risk Number for JS/TS via tree-sitter.
- `scripts/oversight/validators/rn_calculator.py` — Dai et al. (2024) Risk Number for Python source files.
- `scripts/oversight/validators/schema.py` — shared output contract for all oversight validators.
- `scripts/oversight/validators/static_analysis_js.py` — semgrep JS/TS security findings as a risk score.
- `scripts/oversight/validators/static_analysis.py` — bandit security findings as a risk score.
