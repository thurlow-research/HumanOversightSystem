# /hos-build-step

Run the full HOS inner-loop pipeline for a single build step.

## What this does

Executes the complete inner-loop for a build step in dependency order:
1. **Pre-coder gate** — validates that a spec, architect GO, and technical design exist for the step
2. **Coder** — implement the step per the technical design
3. **Risk assessor** — score the implementation; validate tier
4. **Review chain** — code-reviewer (blocking) then parallel: security, privacy, reliability, ops reviewers
5. **Sign-off register** — all reviewers write entries
6. **Run validators** — `./scripts/oversight/run_validators.sh`
7. **Second review** — `./scripts/run_second_review.sh --step <N> --tier <tier>`

## Usage

```
/hos-build-step
```

Optionally specify the step number in your message: "Run /hos-build-step for step 3."

## Required before running

- `contract/step-manifest.yaml` exists and names the step
- `docs/specs/SPEC-<N>-*.md` exists (pm-agent approved)
- `docs/architecture/ADR-*.md` exists (architect GO)
- `docs/design/TECHNICAL-DESIGN-*.md` exists (technical-design agent approved)

## What the worker should do

When invoked, the worker should:

1. Read `contract/step-manifest.yaml` to identify the target step
2. Run `./scripts/framework/check_pre_coder_gate.sh <step-slug>` — halt if it fails
3. Dispatch `coder` agent with the technical design as context
4. After coder completes: dispatch `risk-assessor` agent
5. Dispatch `code-reviewer` agent; wait for approval before continuing
6. In parallel: dispatch `security-reviewer`, `privacy-reviewer`, `reliability-reviewer`
7. If the step has UI changes: also dispatch `ui-reviewer`, `a11y-reviewer`
8. If the step has infra changes: also dispatch `infra-reviewer`
9. Run `./scripts/oversight/run_validators.sh`
10. If tier ≥ MEDIUM: run `./scripts/run_second_review.sh --step <N> --tier <tier>`
11. Verify sign-off register is complete; report status to human

The worker must NOT skip any step. If any step fails or escalates, halt and report.
