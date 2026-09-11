# CI execution inventory — CI-portable vs. local-only

*Produced for #1216: "run in CI what can run in CI — replace stamp attestation
with execution where no subscription-auth constraint applies." Enumerates
every gate, validator, and test suite in the local inner-loop pipeline,
classifies it CI-portable or local-only, and records the reason. Read
alongside `docs/GATE-COVERAGE-MECE.md` (which failure classes each layer
catches) — this document answers a narrower question: which layers execute in
GitHub Actions today, and why the rest don't.*

## How to read this table

- **Wired** — runs today in a `.github/workflows/*.yml` job, listed.
- **CI-portable, deferred** — could run in CI (deterministic, no subscription
  auth) but is deliberately not wired in yet, with the specific reason it
  would land red or add no coverage.
- **Local-only** — genuinely cannot run in CI (subscription CLI auth, or a
  network dependency judged too slow/undecided for per-PR gating).

## Gates (`scripts/oversight/gates/*.sh`)

| Gate | Status | Workflow | Reason |
|---|---|---|---|
| `secret_scan.sh` | Wired | `oversight-gates.yml` | Deterministic, file-scoped, no network. |
| `lint_check.sh` | Wired | `oversight-gates.yml` | Deterministic, file-scoped, no network. |
| `type_check.sh` | Wired | `oversight-gates.yml` | Deterministic, file-scoped, no network. |
| `bash_check.sh` | Wired | `oversight-gates.yml` | Deterministic, file-scoped, no network. |
| `portability_check.sh` | Wired | `oversight-gates.yml` | Deterministic, file-scoped, no network. |
| `template_refs_check.sh` | Wired | `oversight-gates.yml` | Deterministic, file-scoped, no network. |
| `django_check.sh` | Wired | `oversight-gates.yml` | Repo-scoped; SKIPs cleanly on a non-Django repo (verified locally against this repo). |
| `astro_check.sh` | Wired | `oversight-gates.yml` | Repo-scoped; SKIPs cleanly on a non-Astro repo (verified locally). |
| `expensive_gates_stub.sh` | Wired | `oversight-gates.yml` | Repo-scoped, static (no Docker daemon needed); SKIPs cleanly with no Dockerfile present (verified locally). |
| `security_scan.sh` | CI-portable, deferred | — | Its pip-audit sub-check scans the CI venv's *installed dependency versions* against a live vulnerability database, not the PR's diff. Verified locally: `run_gates.sh --all` on unmodified `main` fails with 13 pre-existing findings unrelated to any given PR. Wiring it in today lands the check red regardless of PR content — needs either a dependency upgrade pass or a diff-of-audit-output design before it can gate per-PR. |
| `collection_integrity.sh` | CI-portable, deferred (no added coverage) | — | Runs `pytest --collect-only` to catch orphaned imports left by a change that only ran tests scoped to itself — a real gap in the *local* inner loop. In CI, `tests.yml` already runs unscoped `pytest tests/` on every PR, which performs the same collection as a side effect. Wiring this in duplicates that pass for zero additional coverage. Revisit if `tests.yml`'s scope ever narrows to changed-file-relevant tests only. |
| `check_suspension.sh` | Not applicable | — | Sourced helper (suspension-check logic shared by other gate scripts), not a standalone gate. |

## Validators (`scripts/oversight/validators/*.py`) — the 12-dimension risk-assessment suite

| Validator | Status | Workflow | Reason |
|---|---|---|---|
| `rn_calculator.py` / `rn_calculator_js.py` | Wired | `oversight-validators.yml` | Deterministic, file-scoped (Python / JS-TS dispatch matches `run_validators.sh`). |
| `complexity_metrics.py` / `complexity_metrics_js.py` | Wired | `oversight-validators.yml` | Deterministic, file-scoped. |
| `function_metrics.py` / `function_metrics_js.py` | Wired | `oversight-validators.yml` | Deterministic, file-scoped. |
| `n1_detector.py` / `n1_detector_js.py` | Wired | `oversight-validators.yml` | Deterministic, file-scoped. |
| `static_analysis.py` / `static_analysis_js.py` | Wired | `oversight-validators.yml` | Deterministic (bandit/equivalent), file-scoped; 120s budget matches `run_validators.sh`. |
| `hallucination_surface.py` / `hallucination_surface_js.py` | Wired | `oversight-validators.yml` | Deterministic, file-scoped; JS variant also dispatches on `package.json`-only changes (S7, #1063). |
| `portability_check.py` | Wired | `oversight-validators.yml` | Deterministic, file-scoped. |
| `migration_scorer.py` | Wired | `oversight-validators.yml` | Deterministic, all-files-scoped (runs whenever the diff is non-empty). |
| `shell_logic_check.py` | Wired | `oversight-validators.yml` | Deterministic, shell-file-scoped. |
| `diff_size.py` | Wired | `oversight-validators.yml` | Git-only and deterministic; changed-lines/files computed in the workflow. |
| `ip_check.py` | Local-only | — | Calls ScanCode (license gate) + PyPI (regurgitation stub). Runnable in CI in principle but slow — #1216's own body flags this as needing an explicit decision, not a default-yes. Still runs locally and in the outer-loop panel (Level 1+2). |
| `issue_query.py` | Local-only | — | Calls `gh` for historical issue/bug density; network-dependent, not deterministic gate material. |
| `prompt_audit_risk.py` | Local-only | — | Calls `gh` for spec-gap count; same reason as `issue_query.py`. |
| `brownfield.py` | Not applicable | — | Present in the validators directory but not yet wired into `run_validators.sh` locally either — out of scope for #1216, which only concerns validators already in the local pipeline. |
| `schema.py`, `regions.py`, `__init__.py` | Not applicable | — | Shared infrastructure (weights/thresholds, region parsing, package init), not a scored dimension. |

## Test suite

| Suite | Status | Workflow | Reason |
|---|---|---|---|
| `pytest tests/` + coverage gate | Wired, **required** | `tests.yml` | Runs `scripts/framework/run_tests.sh`, the same entry point used locally — no local/CI divergence. Promoted to a required status check by explicit human ruling on #1244 (2026-09-10); `mutmut` (`--mutation`) is intentionally not run per-PR (too slow to run per mutant on every PR). |

## Static analysis outside the gate/validator suites

| Check | Status | Workflow | Reason |
|---|---|---|---|
| `shellcheck --shell=bash` | Wired, **required-check status undecided** | `shellcheck.yml` | Runs on every PR; its own header states findings "block the PR" (#768), but `shellcheck` is **not** listed in `scripts/framework/setup_branch_protection.sh`'s `required_status_checks.contexts` (only `require-overseer-approval`, `require-human-approval`, `require-tier-ceiling`, `tests`). This is the exact "runs but isn't a required check" gap #1216 asked to have a decision recorded on. Promoting it needs the same human ruling `tests.yml` needed for #1244 — protected-surface/governance-policy change, not made by this entry. |

## Subscription-CLI-dependent — local-only by design (D5), not attempted in CI

| Item | Reason |
|---|---|
| `run_second_review.sh` (agy MEDIUM+, codex HIGH+) | Subscription CLI auth cannot be provisioned in CI. |
| `run_panel.sh` (agy + codex + IP agent + Copilot) | Same. |
| `spec-red-team` agent (uses agy) | Same. |
| `framework-validator`'s `validate_agents.sh` semantic pass (agy + codex) | Same — this is what `validation-check.yml`'s content-hash stamp attests to (see below). |

## The validation stamp's scope

`validation-check.yml` / `scripts/framework/check_validation_current.sh` verify
a content-hash stamp (`phase1-<HASH>.stamp`, keyed on the SHA-256 of all
`.claude/agents/*.md` content) rather than re-running anything. This is
**already scoped to the local-only agy/codex semantic review of agent files**
(`framework-validator`'s "phase 1"), not to gates, validators, or tests — that
narrowing landed with `e1ae14a4` (#552, content-hash stamps, 2026-06-28),
**before** #1216 was filed (2026-08-02). #1216's own "Current state" section
describes an older timestamp-based, all-changed-files stamp design that #552
had already replaced; that description was stale at filing time. No code
change was needed here — the stamp does not, and never has (since #552),
implied coverage of anything CI now executes directly (gates, validators,
tests). Nothing in this document's "Wired" rows overlaps with what the stamp
attests.

## Governance/approval workflows — out of scope for this inventory

`require-human-approval.yml`, `require-overseer-approval.yml`,
`require-tier-ceiling.yml`, `label-swap.yml`, `rerun-gate-checks.yml` are
approval-gate and label-plumbing workflows, not review/validator/test
execution — #1216 is about replacing *attestation* with *execution*, and
these were never attestation for execution in the first place.

## Summary — what remains open on #1216 after this document

- **Shellcheck required-check status** — needs an explicit human ruling
  (same precedent as #1244 for `tests.yml`). Not decided here.
- Everything else in #1216's acceptance criteria (inventory, CI-portable
  items wired, `pytest` required, stamp scope) is complete as of this
  document.
