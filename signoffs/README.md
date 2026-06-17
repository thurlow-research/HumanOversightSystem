# Sign-off stamps — CI-enforceable validation suite gate

This directory holds **committed sign-off stamps**, organized per build step as `<step-id>/<role>.stamp` — one per reviewer role in the validation suite, per step. They are the CI-enforcement layer for sign-offs: the markdown sign-off register (`.claudetmp/signoffs/step{N}-register.md`, ephemeral) is what agents write for the oversight-evaluator to reason over; these stamps are what a gate can check mechanically, in CI, after a PR is opened.

Per-step subdirectories (`signoffs/<step-id>/`) keep concurrent PRs for different steps from colliding on a flat stamp namespace (#366). The `<step-id>` is the `id` field from `contract/step-manifest.yaml` (filesystem-safe: alphanumeric and hyphen only).

This is the same pattern as the framework validation stamps (`scripts/framework/validation-stamps/`) applied to per-step sign-offs — see `research/findings/stamp-based-ci-enforcement.md`.

## How it works

The authoritative clock is the **git commit timestamp**, not file mtime (mtime resets on checkout/clone; commit time is immutable history).

1. Make changes (uncommitted).
2. Each reviewer runs `scripts/oversight/sign_off.sh <role> --step <step-id>` → writes `signoffs/<step-id>/<role>.stamp`.
3. `git add -A && git commit` — changed files and stamps share commit time T.
4. The gate (`scripts/oversight/signoff_gate.py`) checks: every required role for the step has a committed stamp **no older than** the newest changed file. Committing new changes after signing, without re-signing, makes the stamp stale → gate fails. That is exactly what it exists to catch.

## Commands

```bash
# Sign off a role for a step (writes the stamp; you commit it):
scripts/oversight/sign_off.sh code-review --step 3 --agent code-reviewer --note "clean"

# Gate, PR/CI mode (files changed vs merge-base; --step is required):
scripts/oversight/signoff_gate.py --base origin/main --step 3

# Gate, deploy mode (every tracked file; iterates every manifest step):
scripts/oversight/signoff_gate.py --all
```

Required roles are read **per step** from `required_signoffs` in `contract/step-manifest.yaml`, mapped to agents via `role_mappings`. PR mode checks only the named step; deploy (`--all`) mode iterates every step in the manifest (manifest-authoritative — a missing `signoffs/<step-id>/` for a step with required roles is a gate failure). A `signoffs/<dir>/` with no matching manifest step (an orphan) is also a gate failure.

## Stamp status values

| Status | Meaning |
|---|---|
| `APPROVED` | Role reviewed, no blocking issues |
| `CONDITIONAL` | Passes, but a human must verify a conditional item before merge |
| `NOT_APPLICABLE` | Role explicitly out of scope for this change (stamp-level equivalent of the N/A register entry) — still must be re-affirmed after later changes, so a role can never silently fall behind |

`ESCALATED` is intentionally **not** a stamp status: an unresolved escalation is by definition not satisfied, so it has no passing stamp and the gate fails (missing stamp) until the escalation is resolved and the role re-signed. A human-authorized waiver is handled by **gate suspension** (`contract/gate-suspension.md`), not by a stamp.

## Environment note

Both scripts use the oversight venv's Python (`scripts/oversight/.venv`) for YAML parsing, falling back to bare `python3` only if the venv is absent. This avoids the PEP 668 / externally-managed crash on macOS Homebrew and Ubuntu 24.04+ where the system Python lacks PyYAML.
