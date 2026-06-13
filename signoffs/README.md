# Sign-off stamps — CI-enforceable validation suite gate

This directory holds **committed sign-off stamps** (`<role>.stamp`), one per reviewer role in the validation suite. They are the CI-enforcement layer for sign-offs: the markdown sign-off register (`.claudetmp/signoffs/step{N}-register.md`, ephemeral) is what agents write for the oversight-evaluator to reason over; these stamps are what a gate can check mechanically, in CI, after a PR is opened.

This is the same pattern as the framework validation stamps (`scripts/framework/validation-stamps/`) applied to per-step sign-offs — see `research/findings/stamp-based-ci-enforcement.md`.

## How it works

The authoritative clock is the **git commit timestamp**, not file mtime (mtime resets on checkout/clone; commit time is immutable history).

1. Make changes (uncommitted).
2. Each reviewer runs `scripts/oversight/sign_off.sh <role>` → writes `signoffs/<role>.stamp`.
3. `git add -A && git commit` — changed files and stamps share commit time T.
4. The gate (`scripts/oversight/signoff_gate.py`) checks: every required role has a committed stamp **no older than** the newest changed file. Committing new changes after signing, without re-signing, makes the stamp stale → gate fails. That is exactly what it exists to catch.

## Commands

```bash
# Sign off a role (writes the stamp; you commit it):
scripts/oversight/sign_off.sh code-review --agent code-reviewer --note "clean"

# Gate, PR/CI mode (files changed vs merge-base):
scripts/oversight/signoff_gate.py --base origin/main

# Gate, deploy mode (every tracked file):
scripts/oversight/signoff_gate.py --all
```

Required roles are the union of every step's `required_signoffs` in `contract/step-manifest.yaml`, mapped to agents via `role_mappings`.

## Stamp status values

| Status | Meaning |
|---|---|
| `APPROVED` | Role reviewed, no blocking issues |
| `CONDITIONAL` | Passes, but a human must verify a conditional item before merge |
| `NOT_APPLICABLE` | Role explicitly out of scope for this change (stamp-level equivalent of the N/A register entry) — still must be re-affirmed after later changes, so a role can never silently fall behind |

`ESCALATED` is intentionally **not** a stamp status: an unresolved escalation is by definition not satisfied, so it has no passing stamp and the gate fails (missing stamp) until the escalation is resolved and the role re-signed. A human-authorized waiver is handled by **gate suspension** (`contract/gate-suspension.md`), not by a stamp.

## Environment note

Both scripts use the oversight venv's Python (`scripts/oversight/.venv`) for YAML parsing, falling back to bare `python3` only if the venv is absent. This avoids the PEP 668 / externally-managed crash on macOS Homebrew and Ubuntu 24.04+ where the system Python lacks PyYAML.
