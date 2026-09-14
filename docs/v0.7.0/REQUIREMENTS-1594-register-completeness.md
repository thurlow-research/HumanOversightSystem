# REQUIREMENTS-1594 — Make `check_register_completeness()` able to fire correctly

Issue: #1594 (priority:critical, milestone v0.7.0). Epic: #1358.
Author: pm-agent. Date: 2026-09-14.

## Problem (restated as product behavior)

The overseer's step-4a register-completeness bounce is inert. Two compounding
defects, which must be fixed together:

- **F1 — silently never fires.** `contract/step-manifest.yaml` does not exist in
  this repo (only `contract/step-manifest.template.yaml`).
  `_required_signoffs_for_step()` (`merge_authority.py:838`) returns `[]`,
  `check_register_completeness()` short-circuits at `:906-909`, and the register
  is never read. No PR has ever been checked.
- **F2 — unconditionally fires.** Add a manifest with real content and the gate
  reads `.claudetmp/signoffs/step{N}-register.md` (`_bounce_register_path()`,
  `:798-799`). `.claudetmp/` is gitignored ephemeral state (OVERSIGHT-CONTRACT §1).
  The overseer runs in a **separate clone** that never had the worker's session
  state, so `read_text()` raises `OSError` and every PR bounces.

Precedent for the correct shape: step 3b reads
`signoffs/validators/step{N}/summary.json` (`pr_readiness.py:110-111`) — a
**committed** path that travels with the branch.

## Findings the design must build on

**Nothing in `scripts/` or `bin/` writes the register.** Grep for
`.claudetmp/signoffs` returns *readers* only (`merge_authority.py`,
`pr_readiness.py`). Every writer is an **agent prompt** writing the file with its
own Write tool:
`code-reviewer`, `security-reviewer`, `privacy-reviewer`, `reliability-reviewer`,
`ops-reviewer`, `ui-reviewer`, `a11y-reviewer`, `infra-reviewer`, `unit-test`,
`system-test`, `pm-agent`, `ux-designer`, `post-change-sweep` (N/A entries), and
`oversight-evaluator` (the §3 commit-range header). Consequently a relocated
*read* path with no writer change is the same bug moved.

**`contract/step-manifest.yaml` has five other consumers**, all currently inert
in this repo because the file is absent: `signoff_gate.py` (derives the required-
role union), `release_artifact_logic.py`, `sign_off.sh`, `gate_compliance.gates_required()`,
and `cut_release.sh` (`[[ -f ... ]]` guard). Creating the file **activates all of
them**.

## Requirements

**R1 — The manifest must exist and must describe this repo's real steps.**
`contract/step-manifest.yaml` (committed) with `contract_version`, `project`,
`role_mappings`, and a `steps:` list, per `step-manifest.template.yaml`.
`role_mappings` may only name roles that have a real agent in `.claude/agents/`.
Role keys come from OVERSIGHT-CONTRACT §3: `code-review`, `security`, `privacy`,
`reliability`, `ops`, `ui`, `a11y`, `infra`, `test-unit`, `test-system`, `process`.

**R2 — An unknown step id must not read as "nothing is required."**
`_required_signoffs_for_step()` today returns `[]` for three distinct cases:
manifest absent, step id absent from the manifest, and step declaring an
explicitly empty list. Only the third is "nothing required." The other two are
**configuration gaps and must fail closed** (bounce with a reason distinguishing
them from a register gap). Collapsing them is failure mode F1 in a new costume.

**R3 — The register must live where both sessions can read the same bytes.**
Constraint handed to the architect (the architect chooses the path/layout):
  1. git-committed and present on the PR branch, so it travels to any clone with
     that commit checked out;
  2. written **before** the PR is opened (worker step 8.9 ordering), not after;
  3. populated only with fields **current writers already emit** — the §3 schema
     (`Status`, `Agent`, `Artifact`, `Iterations`, plus optional
     `Critical_findings_resolved` / `Human_resolution` / `Notes` / header
     `base_sha` / `head_sha`). No new required field may be introduced that no
     existing writer populates;
  4. concurrency-safe across simultaneous PRs — two branches must not collide on
     one path (precedent: per-branch namespacing, `signoffs/<namespace>/`, #968;
     and `signoffs/validators/step{N}/`);
  5. `.claudetmp/` must remain valid as *working* state; this requirement is
     about the artifact the gate reads, not about banning scratch files.

**R4 — Every writer moves with the read path.** All 14 agent prompts listed above
must be updated in the same change set, together with the docs that specify the
path: `contract/OVERSIGHT-CONTRACT.md` §1 and §3, `ARCHITECTURE.md:240`,
`docs/OVERSIGHT-RUNBOOK.md`, `signoffs/README.md`,
`docs/v0.3.0/BASE-AGENTS-SPEC.md`, `.claude/commands/hos-review-pr.md`,
`overseer.md` (:197, :235, :283), `worker.md:380`. A partial migration is worse
than no migration: it produces a register that some roles write and the gate
cannot see, i.e. a false bounce that looks like a real one.

**R5 — The two gates must not diverge.** `pr_readiness.py` REQ-W-05/06
(`_register_path()` :114-115, `_STEP_MANIFEST_DEFAULT` :91) and
`merge_authority.check_register_completeness()` must resolve the register path
and the manifest path through a **single shared helper**, so worker-side and
overseer-side can never disagree about where "the" register is. The worker-side
gate "works" today only by accident of same-clone/same-session timing.

**R6 — Any compatibility fallback must be observable and must not be a bypass.**
If a fallback read of the legacy `.claudetmp/` path is retained for consumer
projects mid-upgrade, it must (a) be read-only, (b) be recorded in the result so
a human can see it was used, and (c) never be the sole reason a PR passes in a
clone other than the authoring one. A silent fallback re-creates F1.

**R7 — Activating the manifest must not silently flip unrelated gates.**
Creating `contract/step-manifest.yaml` turns on `signoff_gate.py`,
`release_artifact_logic.py`, `sign_off.sh`, `gates_required()`, and
`cut_release.sh`'s manifest branch. Any gate that changes from inert to blocking
must be a **deliberate, documented** decision in the technical design, not a side
effect discovered in CI.

**R8 — A bounce must be diagnosable.** `RegisterCompletenessResult.summary` must
name the resolved register path, the step id used, and which of {manifest
missing, step unknown, register missing, role missing, field missing, unresolved
escalation} fired.

## Non-goals (do not scope-creep)

- **#1357** — no CLI invocation wrapper for `check_register_completeness()`. This
  issue fixes what the function *returns*, not how it is invoked.
- **#1356** — do not touch the bounce counter / `record_pr_bounce`.
- No change to OVERSIGHT-CONTRACT §7 conditions 1-3 *semantics*, no new register
  fields, no change to the `.stamp` gate (`signoff_gate.py`) beyond whatever R7
  documents.

## Acceptance criteria

- **AC-1** `contract/step-manifest.yaml` exists, is committed, and every role key
  in it maps to an agent that exists in `.claude/agents/`.
- **AC-2** With the manifest present and a complete register on the branch,
  `check_register_completeness()` returns `bounce_required=False` **when called
  from a clone that did not author the branch** (test: fresh checkout / temp repo
  with only committed files). This is the direct F2 regression test.
- **AC-3** With the manifest present, a required role's entry absent from the
  committed register → `bounce_required=True`, `failures` names the role,
  `reason_category="REGISTER_GAP"`.
- **AC-4** Manifest absent → `bounce_required=True` with a reason distinct from
  `register-missing` (F1 regression test). Must NOT return `False`.
- **AC-5** Step id not present in the manifest → `bounce_required=True`, reason
  distinct from both AC-3 and AC-4 (F1 regression test).
- **AC-6** A step whose `required_signoffs` is **explicitly empty** →
  `bounce_required=False`. This is the only surviving "nothing required" path.
- **AC-7** `test_no_required_roles_passes_even_without_register`
  (`tests/automation/test_bounce_gate.py:81`) is **renamed and narrowed** to the
  AC-6 case (suggested: `test_explicitly_empty_required_signoffs_passes`); its
  `_write_manifest(tmp_path, [])` fixture already writes an explicit empty list,
  so the assertion stays valid — what changes is that it no longer stands in for
  AC-4/AC-5, which get their own tests. Leaving it unrenamed is a fail: its
  current name asserts the broken behavior is correct.
- **AC-8** A test proves `pr_readiness.py` and `merge_authority.py` resolve the
  same register path for the same step (R5) — e.g. both call the shared helper,
  asserted directly.
- **AC-9** Every agent prompt listed in R4 references the new path; a grep for
  the legacy path across `.claude/agents/`, `contract/`, `docs/` returns only
  intentional historical/migration mentions.
- **AC-10** An end-to-end check on a real HOS PR branch: the register the worker
  writes for step N is readable by `check_register_completeness()` in the
  overseer clone at the PR head commit.
- **AC-11** The existing suite (`scripts/framework/run_tests_inner_loop.sh`)
  passes, including any gate newly activated per R7.

## Open question for the architect (not for the coder to decide)

R3's exact path and layout — a per-branch namespaced markdown register under
`signoffs/`, a per-step directory mirroring `signoffs/validators/step{N}/`, or a
different shape. The product constraint is R3 (1)-(5); the mechanism is an
architecture decision.

## Escalation flag (CORE self-flag)

RISK: MEDIUM
CONFIDENCE: 85% — confident about the two failure modes, the writer inventory
(grep-verified: no script writes the register), and the manifest's five other
consumers. Not confident which step ids this repo's issue-driven worker actually
emits; only `signoffs/validators/step1/` exists on main, so the step-id domain
needs confirming during design.

Classification: **structural**. R3/R4 relocate a path that
`contract/OVERSIGHT-CONTRACT.md` §1 defines normatively, and R7 may flip
currently-inert gates to blocking. Both change existing approved behavior.

## Human Review Required

**`contract/OVERSIGHT-CONTRACT.md` §1 / §3** — the register path is contract
text. Moving it out of `.claudetmp/` requires human sign-off **before** the
contract is edited; this document proposes the constraint, it does not authorize
the edit.
**`contract/step-manifest.yaml` (new file)** — a human should confirm the
per-step `required_signoffs` for this repo, since that list is what every future
PR will be gated on, and it simultaneously activates `signoff_gate.py`'s
required-role union (R7).
