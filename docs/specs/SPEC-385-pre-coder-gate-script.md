# Requirements Spec — Issue #385: check_pre_coder_gate.sh

**Document type:** Requirements specification
**Status:** Draft
**Issue:** #385
**Date:** 2026-06-16
**Author:** pm-agent

---

## 1. Problem Statement

The worker agent (worker.md) is required to dispatch pm-agent, architect, and technical-design before dispatching the coder. This pipeline is currently enforced by a prose checklist that the worker reasons around when it classifies a change as small. A prose gate is advisory; a failing script is structural. This spec defines a deterministic shell script that encodes the gate as a hard mechanical check the worker cannot rationalize past.

---

## 2. Scope

This spec covers:
- The script `scripts/framework/check_pre_coder_gate.sh`
- The worker.md CORE edit that replaces the prose checklist with a script invocation
- A unit test for the script (mocked file checks)

This spec does not cover:
- How the worker dispatches the missing pipeline agent after a gate failure (existing worker routing logic handles that)
- Changes to any other agent or any other gate

---

## 3. Requirements

### 3.1 Script location and interface

**REQ-385-01:** The script MUST be created at `scripts/framework/check_pre_coder_gate.sh`.

**REQ-385-02:** The script MUST accept exactly one positional argument: `<feature-slug>`. Usage:
```
check_pre_coder_gate.sh <feature-slug>
```
A slug is the kebab-case identifier used to name spec, technical design, and architect temp files (e.g. `evaluator-re-derivation`, `pre-coder-gate-script`).

**REQ-385-03:** The script MUST be executable (`chmod +x`) and begin with `#!/usr/bin/env bash`.

**REQ-385-04:** The script MUST exit 0 if and only if all three gate conditions in §3.2 are satisfied simultaneously.

**REQ-385-05:** The script MUST exit 1 if any gate condition is not satisfied.

**REQ-385-06:** On exit 1, the script MUST print a specific error message to stderr naming the unsatisfied condition(s). Each unsatisfied condition MUST produce a separate error line. The script MUST evaluate all three conditions before exiting — it does not short-circuit on the first failure.

**REQ-385-07:** The script MUST accept no flags other than `--help` (which prints usage and exits 0). Unknown flags exit 2.

**REQ-385-08:** If called with no arguments or more than one positional argument, the script MUST exit 2 with a usage error.

### 3.2 Gate conditions

#### Condition 1 — Spec file exists and is committed

**REQ-385-09:** The script MUST check that a file matching `docs/specs/SPEC-{slug}.md` exists on disk.

**REQ-385-10:** The script MUST check that the same file is tracked and committed in the current git repository (i.e., `git ls-files --error-unmatch docs/specs/SPEC-{slug}.md` exits 0). A file that exists on disk but is untracked or has only been staged (not committed) MUST be treated as not committed.

**REQ-385-11:** On failure of condition 1, the error message MUST identify the missing or uncommitted spec file by its expected path.

#### Condition 2 — Technical design exists and is committed

**REQ-385-12:** The script MUST check that a file matching the glob `docs/v*/TECHNICAL-DESIGN-{slug}.md` exists on disk. If multiple matches exist, the check passes if at least one match exists.

**REQ-385-13:** The script MUST check that at least one matching technical design file is tracked and committed in the current git repository (`git ls-files` with the glob pattern). A file on disk but not committed MUST be treated as not committed.

**REQ-385-14:** On failure of condition 2, the error message MUST identify the expected path pattern and state whether the file was absent or present but uncommitted.

#### Condition 3 — No open REQUEST_CHANGES verdict from architect

**REQ-385-15:** The script MUST check all files matching the glob `.claudetmp/design/architect-{slug}-*.md`.

**REQ-385-16:** For each matching file, the script MUST read the file and extract the LAST `status:` line (case-insensitive key, value must be checked case-insensitively). If the last `status:` line in any matching file is `REQUEST_CHANGES`, that file represents an open rejection.

**REQ-385-17:** If any matching architect file has `status: REQUEST_CHANGES` as its last verdict, condition 3 MUST be treated as failed.

**REQ-385-18:** If no files match `.claudetmp/design/architect-{slug}-*.md`, condition 3 MUST be treated as **passed** (absence of a REQUEST_CHANGES verdict is not a gate failure — the spec and technical design files in conditions 1 and 2 are the positive evidence of architect review).

**REQ-385-19:** On failure of condition 3, the error message MUST name the file(s) containing the open REQUEST_CHANGES verdict.

### 3.3 Error message format

**REQ-385-20:** Each error line MUST begin with `[GATE FAIL]` followed by the condition label and a human-readable description. Example format (exact wording may vary, but the structure is required):
```
[GATE FAIL] SPEC: docs/specs/SPEC-evaluator-re-derivation.md not found or not committed
[GATE FAIL] TECH-DESIGN: no committed file matching docs/v*/TECHNICAL-DESIGN-evaluator-re-derivation.md
[GATE FAIL] ARCHITECT: .claudetmp/design/architect-evaluator-re-derivation-20260616.md has status: REQUEST_CHANGES
```

**REQ-385-21:** On exit 0, the script MUST print a single confirmation line to stdout:
```
[GATE PASS] pre-coder gate satisfied for slug: <slug>
```

### 3.4 Git context

**REQ-385-22:** The script MUST determine the git root by running `git rev-parse --show-toplevel` and evaluate all paths relative to that root, not relative to the current working directory. This makes the script safe to invoke from any subdirectory of the repo.

**REQ-385-23:** If `git rev-parse --show-toplevel` fails (not a git repo), the script MUST exit 2 with an error message.

### 3.5 worker.md integration

**REQ-385-24:** The pre-coder gate section of worker.md CORE MUST be updated to replace the prose checkbox list with an explicit script invocation. The new prose MUST state:

> Before dispatching coder for `<feature-slug>`, run:
> `bash scripts/framework/check_pre_coder_gate.sh <feature-slug>`
> If exit != 0: read the GATE FAIL lines, dispatch the missing pipeline agent (pm-agent for a missing spec, technical-design for a missing technical design, architect for an open REQUEST_CHANGES verdict), and do not dispatch coder.

**REQ-385-25:** The worker.md update is a CORE edit. It MUST be delivered in the same commit or PR as the script itself.

### 3.6 Unit test

**REQ-385-26:** A unit test for the script MUST be created (location to be determined by technical-design; the test runner is `scripts/framework/run_tests_inner_loop.sh`).

**REQ-385-27:** The unit test MUST cover at minimum:
- All three conditions passing simultaneously (exit 0)
- Condition 1 failing because the spec file is absent (exit 1, correct GATE FAIL line)
- Condition 1 failing because the spec file exists but is not committed (exit 1)
- Condition 2 failing because no technical design file matches the glob (exit 1)
- Condition 2 failing because a matching file exists but is not committed (exit 1)
- Condition 3 failing because an architect file has `status: REQUEST_CHANGES` as its last status line (exit 1)
- Condition 3 passing when the last status line is `status: APPROVED` even if an earlier line is `REQUEST_CHANGES` (exit 0, confirming last-line semantics)
- Condition 3 passing when no architect temp files exist for the slug (exit 0)
- No arguments provided (exit 2)
- Invoked from a subdirectory (exit 0 when gate passes, confirming git-root resolution)

**REQ-385-28:** The unit test MUST use mocked or temporary file structures — it MUST NOT depend on the actual state of the working tree.

---

## 4. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-385-01 | Script exists at `scripts/framework/check_pre_coder_gate.sh` and is executable |
| AC-385-02 | Exit 0 when all three conditions are satisfied |
| AC-385-03 | Exit 1 with a GATE FAIL line for each unsatisfied condition; all three conditions evaluated before exit |
| AC-385-04 | Exit 2 on usage errors (no args, unknown flag, not in git repo) |
| AC-385-05 | Condition 1 checks both disk presence AND committed status |
| AC-385-06 | Condition 2 accepts any `docs/v*/` directory prefix |
| AC-385-07 | Condition 3 uses last-`status:`-line semantics, not first |
| AC-385-08 | Condition 3 passes when no architect temp files exist for the slug |
| AC-385-09 | Paths resolved relative to git root, not cwd |
| AC-385-10 | worker.md CORE updated to invoke the script (prose checklist removed) |
| AC-385-11 | Unit test covers all scenarios listed in REQ-385-27 |
| AC-385-12 | Unit test passes under `run_tests_inner_loop.sh` |
| AC-385-13 | Script and worker.md change delivered in the same PR |

---

## 5. Open Questions for Architect

**OQ-385-A:** The slug is a free-form string. Should the script validate slug format (e.g. reject slugs containing spaces or slashes) or accept any string and let the glob produce zero results naturally? Recommend: validate and exit 2 on malformed slug, but deferring to architect on the exact allowed character set.

**OQ-385-B:** Condition 3 checks `.claudetmp/design/architect-{slug}-*.md`. Is `.claudetmp/design/` the canonical path for architect verdict files, or should the script also check `.claudetmp/` directly? Worker.md does not specify the subdirectory structure of `.claudetmp/`; technical-design should confirm the canonical path.

**OQ-385-C:** Should the script be invoked from `run_tests_inner_loop.sh` as a standing check (running against all in-progress slugs), or is it exclusively an on-demand gate the worker runs before a specific coder dispatch? The issue says "the worker uses it before coder dispatch" — but if it is also in the inner-loop test suite, the test coverage of REQ-385-26/27 must be reconciled with that usage.

**OQ-385-D:** The "committed" check uses `git ls-files`. On the first commit of a new file (staged but not yet committed), this returns empty. Is staged-but-not-committed acceptable for any of the three conditions? The issue text says "not just on disk" and "exists and is committed," so the answer appears to be no — but architect should confirm whether a staged file (in an active amend) is an edge case worth handling differently.
