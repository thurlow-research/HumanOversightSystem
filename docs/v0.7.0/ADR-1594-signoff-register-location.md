# ADR-1594 — The register is promoted, not relocated: a committed per-branch copy of an unchanged ephemeral artifact, produced as a forced side effect of the pre-PR gate

**Status:** ACCEPTED FOR DESIGN — binds `technical-design`. **Three items are held for the human** (§5): ESC-1 (the `cut_release.sh` activation flip — an operational-obligation change), ESC-2 (confirm the per-step `required_signoffs`, which pm-agent already flagged), ESC-3 (a newly-found defect that makes the worker-side gate uninvocable as documented). Everything else below is **BINDING**.
**Date:** 2026-09-14
**Author:** architect
**Inputs:** `docs/v0.7.0/REQUIREMENTS-1594-register-completeness.md` (pm-agent, 2026-09-14); issue #1594 (priority:critical, v0.7.0); epic #1358; my own re-derivation against the working tree at `b8c6a93b` (§0).
**Consumers:** `technical-design` (next), then `coder`.
**Source issues:** #1594 (this), #1357 (invocation wrapper — **hard prerequisite for the gate to ever execute**, §0 AF-1), #1356 (bounce counter — untouched), #1125 (the gate's origin), #555 (the committed-validator-artifact precedent this ADR copies), #968 (per-branch namespacing), #1500 (the self-heal-then-require-a-commit precedent), #1162 (`submit_pr.sh` pushes committed refs only).
**Explicitly does NOT re-litigate:** the two failure modes F1/F2, the writer inventory, or the manifest's consumer list — pm-agent established all three and §0 confirms them.

---

## 0. Verification — every load-bearing premise re-derived this session

### Confirming pm-agent

- **F1 CONFIRMED.** `merge_authority._required_signoffs_for_step()` (`:838-873`) returns `[]` on `OSError`, on an unmatched step id, and on an explicit empty list. `check_register_completeness()` (`:906-909`) short-circuits `bounce_required=False` on `not required_roles`. `contract/step-manifest.yaml` does not exist.
- **F2 CONFIRMED, and worse in the prose than in the code.** `_bounce_register_path()` (`:798-799`) returns `.claudetmp/signoffs/step{N}-register.md`; `.claudetmp/` is the only entry on line 2 of `.gitignore`. `overseer.md:197` instructs the overseer to read it with `git show origin/main:.claudetmp/signoffs/step{N}-register.md` — a command that **cannot ever succeed**, for any PR, in any clone, because the path is gitignored and therefore never in any commit. The documented overseer procedure is not merely fragile across clones; it is impossible.
- **Writer inventory CONFIRMED.** Nothing in `scripts/`, `bin/`, or `bootstrap/` writes the register. All 14 writers are agent prompts.
- **Precedent CONFIRMED and it is stronger than pm-agent claims.** `run_validators.sh:513-551` already implements exactly the mechanism this ADR adopts: the validators write `.claudetmp/oversight/validators/summary.json` (ephemeral, unchanged), and when `--step` is supplied the script writes a **committed copy** at `signoffs/validators/step{N}/summary.json`, stamped with `head_sha`, `head_sha_source`, `artifact_version`, `written_at`. `pr_readiness.py:110-111` and the overseer's step 3b read that committed copy cross-clone. This is #555, it shipped, and it works.

### My own findings — these change the design

**AF-1 (CRITICAL — `check_register_completeness()` has no non-test caller, so #1594 alone cannot make the gate fire).** `grep -rn "check_register_completeness"` across the repo returns: the definition (`merge_authority.py:887`), `tests/automation/test_bounce_gate.py` (eight call sites), prose in `.claude/agents/overseer.md:278`, and documentation. **There is no executing caller anywhere.** This is ADR-1604's AF-1 class verbatim — *a control whose invocation is an instruction to an agent is a control that never runs*. Consequence, and it must be stated in the PR body rather than discovered later: **this issue makes the function correct; #1357 makes it execute.** Neither alone closes the epic. AC-10 ("an end-to-end check on a real HOS PR branch") is therefore **not** demonstrable through the live overseer path in this changeset and must be met by direct invocation against a fresh clone of the PR head — see AD-8.

**AF-2 (HIGH — the promoted artifact will not reach the PR unless the gate demands a commit).** `bootstrap/submit_pr.sh` contains no `git add` and no `git commit`; it pushes `refs/heads/${HEAD}` explicitly (`:145-161`). A promotion that writes only to the working tree is invisible to the PR and to every other clone. The mitigation already exists in this repo as a shipped pattern: `pr_readiness.py`'s REQ-W-01 comment (`:24-27`, #1500) records that a self-heal must be confirmed *in a commit*, not merely in the post-self-heal working tree. AD-3 copies it.

**AF-3 (HIGH — creating the manifest hard-blocks the next release, and this is the only one of R7's five consumers that actually flips).** Taking them one at a time, grep-verified:
- `signoff_gate.py` — **no invocation site exists anywhere** in `.github/`, `scripts/`, `bin/`, `bootstrap/`, or `contract/`. Every hit is prose. Creating the manifest activates *nothing*; it only defines a future required-role union. (It is additionally already fail-closed without a manifest: `:354-357` exits 2 rather than passing an empty suite.)
- `gate_compliance.gates_required()` — returns `False` on a missing manifest and on a step that does not declare `gates_required: true`. Manifest v1 declares it nowhere, so the value is unchanged. No flip.
- `sign_off.sh:108-121` — `yaml.safe_load(open(MANIFEST))` on an absent file raises today, so the script is currently **broken**, not inert. The manifest repairs it. Strict improvement.
- `release_artifact_logic.py` via `cut_release.sh:200` — **this one flips, and it blocks.** The `[[ -f "contract/step-manifest.yaml" ]]` guard passes `--manifest`, which switches on the sign-off-completeness check (`:368-393`): for every role in the union of all steps' `required_signoffs`, a **committed** `signoffs/<ns>/<role>.stamp` with a valid status must exist, else `escalation_reasons` is populated and the verdict is `escalate` → exit 1 → `cut_release.sh` prints *"Release artifact validation ESCALATED"* and exits. `signoffs/` today contains exactly one thing: `signoffs/validators/step1/summary.json`. **There is not a single `.stamp` file in this repository, and no shipped script writes one automatically** (`sign_off.sh` is a manual, per-role command). The moment this PR merges, every `cut_release.sh` run fails. AD-7 closes this; ESC-1 puts the ops consequence to the human.

**AF-4 (HIGH — this repo has no step-id domain, and R2's fail-closed rule turns that into a universal bounce unless the id is pinned).** The autonomous worker is issue-driven, not plan-step-driven. `bin/hos-cron` and `bootstrap/worker-cron-prompt.md` never assign a step number; no `"step":` field appears in any 2026-09 audit record; the only committed step artifact in the entire repo is `signoffs/validators/step1/`. If the manifest enumerates steps the worker cannot name, R2's "unknown step id must fail closed" converts F1 into an **unconditional bounce** — F2 in a new costume, which is precisely what R2 exists to prevent. AD-5 pins the id.

**AF-5 (MEDIUM — the documented worker-side invocation cannot run at all).** `worker.md:380` (step 8.9) documents `python -m scripts.automation.lib.pr_readiness --cid <cid> --base-sha <base> --head-sha <HEAD>`. The CLI declares `--step` and `--risk-tier` as `required=True` (`:688-690`). The documented command exits 2 on an argparse usage error before any check runs. So REQ-W-05/06 — the worker-side half of R5 — has in all likelihood **never executed as documented**; pm-agent's "works today only by accident of same-clone timing" is generous. Partially addressed by AD-5; the `--risk-tier` half is **ESC-3**.

**AF-6 (MEDIUM — a required role is satisfiable by an N/A entry, which is what makes a non-trivial required set safe).** Contract §3 admits `Status: N/A`, and `post-change-sweep` step 3.5 writes one per skipped reviewer with `Agent:`, `Artifact: —`, `Iterations: 0`. `check_register_completeness()` only fails on a missing entry, an empty required field, or an unresolved `ESCALATED` — it does not inspect `Status` otherwise. So requiring a role costs nothing on a diff that role does not touch, **provided** post-change-sweep's roster covers it. That proviso is a real dependency and is bound in AD-6.

### Verification gaps I could not close

- Whether `post-change-sweep`'s roster is derived from the manifest or from a fixed list — AD-6 makes this a verification obligation on `technical-design` rather than an assumption.
- Whether any consumer project has already created its own `contract/step-manifest.yaml` with a differing step-id convention. The installer copies the **template** to the target (`hos_install.sh:2116-2122`) and never overwrites an existing file, so nothing this ADR adds leaks HOS's own manifest to consumers — but consumer-side step ids are outside what I can see.

---

## 1. Context — what the decision actually is

R3 is usually read as "pick a path". After §0 it is better stated as: **the register's problem is transport, not location.**

Fourteen reviewer agents already write a correct, contract-shaped register. The contract already calls `.claudetmp/` ephemeral working state and is right to. Nothing about the *authoring* of the register is broken. What is broken is that the artifact never crosses the clone boundary, and the one instruction that was supposed to carry it across (`git show origin/main:.claudetmp/...`) describes an impossible operation.

Given that framing, R4's "every writer moves with the read path" is solving the wrong problem — and the cure it prescribes is, on inspection, riskier than the disease. R4's own stated rationale is that *a partial migration is worse than no migration: some roles write where the gate cannot see.* That is an argument against exactly one thing — **a hand-edited, 14-file writer relocation**, which is the only mechanism on the table that can go partial. A promotion step cannot go partial: it copies whatever the register contains, in one operation, for every role at once. The mechanism R4 rejects in principle is the mechanism R4 prescribes in practice.

The choice below is therefore not "cheap vs. correct". It is "copy a shipped, cross-clone-proven pattern (#555) and leave 14 protected-surface governance files untouched" versus "hand-edit 14 protected-surface governance files to obtain a property the copy already has".

---

## 2. Decisions (BINDING on `technical-design`)

### AD-1 — Option A. The register is **promoted**, not relocated. The 14 agent prompts are not edited. (BINDING — resolves R3 and supersedes R4.)

The ephemeral register at `.claudetmp/signoffs/step{N}-register.md` remains the **authoring** surface, written by the same 14 agents, with zero changes to any of them. A promotion step copies it to a **git-committed** path before the PR opens; both gates read the committed copy. Grounds, in order of weight:

1. **It is a shipped pattern in this repo, proven across the exact boundary in question.** #555 promotes the validator summary from `.claudetmp/oversight/validators/summary.json` to `signoffs/validators/step{N}/summary.json`, and the overseer's step 3b reads it from a different clone successfully today. The register gets the same treatment for the same reason. Inventing a second mechanism for the same problem, in the same directory, would be the anomaly.
2. **It is atomic where Option B is not.** One copy operation covers all roles. Option B's failure mode — one of 14 files missed, a register the gate half-sees, a false bounce indistinguishable from a real one — is exactly the failure R4 names, and Option A cannot reach it.
3. **It keeps the contract edit additive.** Under Option A, §1's `.claudetmp/signoffs/` entry stays true, and §3's schema is untouched; the contract gains a *new committed artifact* alongside the existing `signoffs/validators/` entry. Under Option B, §1's normative path is relocated and all 14 agent files plus seven documents must move in lock-step. Additive contract text is a materially smaller human-approval surface on a `contract/**` protected-surface PR.
4. **Option B is not authorable by the pipeline.** Per `CLAUDE.md`, `.claude/agents/*.md` edits are governance-artifact edits that `coder` must refuse; they must be hand-authored by the orchestrating session. Fourteen such files plus the code and tests exceed the ≤15-file / ≤10-commit batching guidance in one PR, and splitting them across PRs reintroduces precisely the partial-migration window R4 forbids. **Option B is the only one of the two options that can produce R4's own nightmare scenario.**
5. **Option B buys no correctness Option A lacks.** Both end with one committed file at one path read by one shared helper. The only real risk Option A adds is *staleness* — a register entry written after the copy — and AD-3 closes that deterministically, in code, without trusting any agent.

**R4 as pm-agent wrote it is superseded and does not apply:** there is no writer relocation to perform, so there is no partial migration to fear. The promotion step becomes the sole writer of the committed artifact, sourced from what the 14 agents already produce unchanged. §6 records this supersession and its sign-off consequences.

**What could still go wrong, stated rather than waved away.** (a) The committed copy can be stale relative to the ephemeral file — closed by AD-3's re-promote-and-require-a-commit loop. (b) The committed copy can be hand-edited after promotion to fabricate a sign-off — but so could a directly-written register under Option B; both are equally forgeable by a PR author and equally visible in the diff, so Option B carries no integrity advantage. (c) Two sources of truth now exist for the same content; AD-2's byte-identity rule and AD-4's no-fallback rule keep the derived one strictly derived.

### AD-2 — Path and layout: `signoffs/<namespace>/step{N}-register.md`, byte-identical to its source, with a provenance sidecar. (BINDING — R3 constraints 1, 3, 4, 5.)

- **Path:** `signoffs/<namespace>/step{N}-register.md`, where `<namespace>` is the existing per-branch slug from #968 — the same value `sign_off.sh:62` and `signoff_gate.py:205` already compute, reused via the existing `signoff_namespace()` helper, **not** re-derived. This satisfies R3.4 (two concurrent PRs are on two branches, so they occupy two directories and can never collide on one path, nor conflict on merge) and puts the register in the same per-branch directory as that branch's `<role>.stamp` files, which is where a reader would look for it.
- **Not** flat `signoffs/step{N}-register.md`, and **not** `signoffs/validators/step{N}/`-style per-step directories: `signoffs/README.md` records that #968 deliberately superseded per-step layout by going finer, because per-step still collides between two PRs on the same step — and under AD-5 *every* PR in this repo is on the same step, so a per-step layout would collide on essentially every concurrent pair.
- **The copy is byte-identical to the ephemeral file.** No header, footer, or field is added. This satisfies R3.3 absolutely: no new field is introduced that no existing writer populates, and the existing §3 grammar parses the committed copy unchanged.
- **Provenance lives in a sidecar,** `signoffs/<namespace>/step{N}-register.provenance.json`, carrying `artifact_version`, `step`, `namespace`, `branch`, `source_path`, `head_sha`, `head_sha_source`, `written_at`, `source_sha256` — the same field set and the same rationale as #555's validator artifact. The sidecar is never required for the gate to pass; it exists for R8 diagnosis and for detecting a hand-edited copy (`source_sha256`).
- `.claudetmp/` remains fully valid as working state (R3.5). Nothing is banned; one artifact is additionally published.

### AD-3 — Promotion is a forced side effect of the pre-PR gate, and the gate fails closed until the copy is **in a commit**. (BINDING — R3.2; AF-2, AF-1's failure class.)

`pr_readiness.py` (worker.md step 8.9) is the mandatory chokepoint immediately before PR creation, it already blocks PR creation on failure, and it already carries the exact precedent (#1500): self-heal in place, then require the result to have reached a commit. Promotion goes there, not into `submit_pr.sh` (too late — REQ-W-05/06 would still be reading the ephemeral path, and R5 would be satisfied only nominally) and not into a new step in `worker.md` (an instruction an agent can skip — ADR-1604 AF-1).

Bound sequence inside `assess_pr_readiness()`, before REQ-W-05/06 run:

1. **Promote**: copy `.claudetmp/signoffs/step{N}-register.md` → `signoffs/<ns>/step{N}-register.md`, atomically (write to a temp file in the destination directory, then `mv` — the #555/#725 pattern), and write the sidecar. Re-promotion is unconditional on every run, so a register entry written after an earlier run is always picked up; there is no staleness window that survives a re-run, and the gate *must* be re-run after any fix because it blocks PR creation.
2. **New check REQ-W-05a — "promoted register is committed at HEAD."** Verify with `git cat-file -e HEAD:signoffs/<ns>/step{N}-register.md` (not a working-tree `exists()`), and verify the committed blob matches the working-tree copy. Fail with an actionable message naming the exact path to `git add` and instructing a re-run. This is the check that makes the mechanism real rather than aspirational: `submit_pr.sh` pushes committed refs only (AF-2), so an uncommitted promotion is a silent no-op without it.
3. **REQ-W-05/06 then read the committed path**, through the shared helper of AD-4 — never the ephemeral one.

*Self-certification objection, answered.* A gate that produces the artifact it checks is normally a smell. Here the gate authors no content: it copies bytes the reviewers wrote and cannot cause a missing role, a missing field, or an unresolved escalation to appear. Promotion guarantees **transport only** — which is the entire defect. Every assertion that can fail is unaffected by the copy.

### AD-4 — One shared module resolves the manifest path, the register path, and the required-signoff set. Both gates call it. No legacy fallback anywhere. (BINDING — R5, R6.)

New module `scripts/automation/lib/signoff_register.py`, stdlib-only (it must not create a cycle: `pr_readiness` already imports from `merge_authority`), exposing at minimum:

- `DEFAULT_STEP_ID` (AD-5);
- `signoff_namespace(root, override=None)` — delegating to, or lifted verbatim from, `signoff_gate.py:205` so all three call sites compute one value;
- `register_relpath(step, namespace)` → `signoffs/<ns>/step{N}-register.md`;
- `promote_register(root, step, namespace) -> PromotionResult`;
- `resolve_required_signoffs(manifest_path, step) -> RequiredSignoffs` (AD-5's four-state result);
- `parse_register(text)` — one grammar, replacing the two deliberately-duplicated parsers in `merge_authority.py:801-834` and `pr_readiness.py:226+`. The original duplication was justified by a circular-import risk (`merge_authority.py:784-789`); a third module that neither imports removes the justification. **AC-8 is asserted directly against this module**: a test proves both gates resolve the identical relpath for the same `(step, namespace)`.

**Namespace resolution for the overseer.** The reader takes the namespace as an explicit parameter (`check_register_completeness(step, *, namespace=...)`), supplied from the PR's head ref by the caller — #1357's wrapper has `pr.head.ref` in the payload it already reads. Defaulting to the local branch slug is correct only in the authoring clone and must not be relied on cross-clone. **Fallback, bounded and fail-closed:** if the exact path is absent, glob `signoffs/*/step{N}-register.md` and select the one whose sidecar `branch` matches the PR head ref. Exactly one match → use it (record that discovery was used, in the summary). Zero → `register-missing`. Two or more → `register-ambiguous`, bounce. Never pick "the newest".

**No `.claudetmp/` fallback is retained — in either gate.** R6 permits one; I decline it, which is the stronger reading of R6's own condition (c). A fallback to the ephemeral path can only ever succeed in the authoring clone, so it would be, by construction, "the sole reason a PR passes in the authoring clone" — R6's named prohibition. Consumer projects mid-upgrade do not need it either: their unmodified agents keep writing `.claudetmp/`, and the upgraded `pr_readiness.py` promotes it for them. The upgrade path works with no fallback, so R6 is satisfied vacuously rather than managed.

### AD-5 — R2: four distinguishable resolutions, and the step id is pinned to a constant. (BINDING — R2, R8; AF-4, AF-5.)

`resolve_required_signoffs()` returns a `RequiredSignoffs` dataclass with `status` in:

| status | condition | gate result |
|---|---|---|
| `MANIFEST_MISSING` | manifest file unreadable/absent | bounce; `failures=["manifest-missing:<resolved path>"]`; `reason_category="CONFIGURATION_GAP"`; `configuration_gap=True` |
| `STEP_UNKNOWN` | manifest parses, no entry with this id | bounce; `failures=["step-unknown:<id>"]`; `reason_category="CONFIGURATION_GAP"`; `configuration_gap=True` |
| `EXPLICIT_EMPTY` | entry exists, `required_signoffs: []` | **no bounce** — the only surviving "nothing required" path (AC-6) |
| `RESOLVED` | entry exists with a non-empty list | proceed to the register checks |

Binding details:

- `"CONFIGURATION_GAP"` is **added** to `_BOUNCE_REASON_CATEGORIES` (`merge_authority.py:793`), which `record_pr_bounce()` validates against at `:1180`. This is inside the function's own return vocabulary and does not touch §7 conditions 1–3 semantics, so it is within pm-agent's non-goals.
- `RegisterCompletenessResult` gains `configuration_gap: bool = False` so a caller can route without string-matching. **Binding on the routing, for #1357 to honour:** a configuration gap is **not worker-fixable** — `contract/**` is the second entry in `scripts/framework/protected_surfaces.txt`, so any manifest correction needs a human-approved PR. Bouncing it to the worker creates an unresolvable loop that looks like progress. A configuration gap must route to `HUMAN_REQUIRED`. #1594 makes the distinction machine-readable; #1357 acts on it.
- **The step id is a pinned constant, not an improvisation.** `DEFAULT_STEP_ID = 1`, used when a caller supplies no step. `pr_readiness.py`'s `--step` gains that default (it is currently `required=True`, and `worker.md:380`'s documented command omits it — AF-5). Without pinning, R2's fail-closed rule converts F1 straight into "every PR bounces with `step-unknown`", because this repo's issue-driven worker has no step-id domain at all (AF-4). `1` is chosen because it is the only step id any committed artifact in this repo uses (`signoffs/validators/step1/`).
- **R8:** `summary` names, in every branch, the resolved register path, the namespace, the step id used, the manifest path, and exactly which of {manifest-missing, step-unknown, register-missing, register-ambiguous, register-missing-role, register-missing-fields, register-unresolved-escalation} fired.

### AD-6 — Manifest v1: one step, one lane, a deliberately narrow required set. (BINDING as a proposal; the values are **ESC-2** for human confirmation, per pm-agent's flag.)

```yaml
contract_version: "1"
project: "HumanOversightSystem"

role_mappings:
  code-review:   code-reviewer
  security:      security-reviewer
  privacy:       privacy-reviewer
  reliability:   reliability-reviewer
  ops:           ops-reviewer
  ui:            ui-reviewer
  a11y:          a11y-reviewer
  infra:         infra-reviewer
  test-unit:     unit-test
  test-system:   system-test
  process:       pm-agent

steps:
  - id: 1
    name: "Issue-driven change (the autonomous worker's only lane)"
    risk_tier: MEDIUM
    required_signoffs: [code-review, test-unit]
    system_test_applicable: false
```

- **All eleven §3 roles are mapped** (AC-1: each maps to a real agent in `.claude/agents/` — verified this session), because `role_mappings` is a vocabulary, not a requirement. Only `required_signoffs` gates.
- **Only `code-review` and `test-unit` are required in v1.** Both are produced on essentially every worker PR (`run_tests_inner_loop.sh` is a hard gate at step 8.7; `code-reviewer` runs on every diff), and both may legitimately be `Status: N/A` when inapplicable (AF-6), so the gate is satisfiable without weakening it.
- **Why not the wider set** (`+ security, privacy, process`): this gate has never fired on any PR in the history of this repo. The first version must be one that fires *correctly*, not one that fires *loudly*. Widening is a one-line manifest edit once AC-10 is demonstrated on a live PR, and it should be its own issue with its own human confirmation. Starting wide risks discovering, on a `priority:critical` PR, that `post-change-sweep`'s N/A roster does not cover a required role — and the union also drives the release stamp gate (AD-7), where each added role is another `.stamp` that nothing yet writes.
- **`gates_required` is declared nowhere** and `human_gate_required` is declared nowhere. Both are deliberate (AD-7). `technical-design` must include a test asserting manifest v1 declares neither, so a later edit that flips `gate_compliance.gates_required()` is a visible, reviewed change.
- **Verification obligation on `technical-design`:** confirm that `post-change-sweep`'s skipped-reviewer roster (step 3.5) covers every role in `required_signoffs`, so a required role is always either signed or explicitly N/A'd. If it does not, say so and escalate rather than widening the required set.

### AD-7 — R7: the release gate's activation is made explicit instead of file-triggered. Nothing else flips. (BINDING — R7; AF-3. Ops consequence is **ESC-1**.)

Per-consumer rulings, all four documented in the PR body so none is discovered in CI:

| Consumer | Effect of creating the manifest | Action |
|---|---|---|
| `signoff_gate.py` | **None.** No invocation site exists anywhere in the repo. | Document; no code change. |
| `gate_compliance.gates_required()` | **None.** v1 declares `gates_required` nowhere, so it still returns `False`. | Test-asserted (AD-6). |
| `sign_off.sh` | **Repaired** — it currently raises on the absent manifest. | Document as an improvement. |
| `release_artifact_logic.py` via `cut_release.sh:200` | **Hard block.** Demands a committed `.stamp` per required role; zero `.stamp` files exist; verdict `escalate` → exit 1 → every release cut fails. | **Changed — see below.** |

**BINDING:** replace `cut_release.sh:200`'s implicit `[[ -f "contract/step-manifest.yaml" ]]` activation with an explicit opt-in — `HOS_RELEASE_REQUIRE_SIGNOFF_STAMPS=1` (default **off**) — carrying an inline comment that names the reason (no shipped writer produces `.stamp` files; `sign_off.sh` is manual and per-role) and references a follow-up issue to turn it on once a stamp writer exists. The other two release-artifact checks (step-artifact sweep, risk-tier/blocking-findings) are **unaffected and keep running**; only the sign-off-completeness check is gated.

This is not weakening a live control. The control has never executed with a manifest present, so there is no behaviour to weaken; what changes is that its first execution becomes a deliberate act rather than a side effect of creating a configuration file. That is the literal text of R7. **It is nonetheless an operational-obligation change to the release process and goes to the human as ESC-1.**

### AD-8 — AC-10 is met by direct invocation against a fresh clone, not by the live overseer. (BINDING — AF-1.)

`check_register_completeness()` has no executing caller (AF-1), so "the overseer clone reads it at the PR head" cannot be exercised end to end in this changeset. AC-10 is satisfied by a test that: clones (or `git worktree add --detach`s) the PR head into a temporary directory containing **only committed files**, calls `check_register_completeness(step, repo_root=<temp>, namespace=<head ref slug>)`, and asserts `bounce_required is False`. That is the real F2 regression test (AC-2) and the strongest available form of AC-10. The PR body must state plainly that the gate remains unexecuted in production until #1357 lands, and #1594 must not be described as closing the epic on its own.

### AD-9 — Scope boundaries.

In scope: `contract/step-manifest.yaml` (new); `scripts/automation/lib/signoff_register.py` (new); `merge_authority.py`; `pr_readiness.py`; `cut_release.sh` (AD-7's guard only); tests; and the documentation that describes the register's location — `contract/OVERSIGHT-CONTRACT.md` §1/§3 (**additive**: a new `signoffs/<namespace>/step{N}-register.md` entry alongside the existing `signoffs/validators/` one; the `.claudetmp/` entry stays and stays true), `signoffs/README.md`, `ARCHITECTURE.md:240`, `docs/OVERSIGHT-RUNBOOK.md`, `.claude/commands/hos-review-pr.md`, and `.claude/agents/overseer.md:197` — the last of which documents an impossible command (§0) and must be corrected to read the committed path. **`overseer.md` is the only `.claude/agents/*.md` file in this changeset; per `CLAUDE.md` it must be hand-authored by the orchestrating session, never by `coder`.** Estimated file count 12–14, within the ≤15 budget.

Out of scope, explicitly: the 14 reviewer agent prompts (AD-1); #1357's invocation wrapper; #1356's bounce counter; any new register field; widening `required_signoffs` (AD-6); writing `.stamp` files (AD-7); `--risk-tier` on the worker-side gate (ESC-3).

---

## 3. Build order

One PR, in this order, so a partial landing is never a live half-gate:

1. `signoff_register.py` + its unit tests (no caller yet — inert).
2. `merge_authority.py` and `pr_readiness.py` switched onto it; `AC-7`'s test renamed and narrowed; AC-2/3/4/5/6/8 tests added. **Still inert**, because the manifest does not exist.
3. `cut_release.sh`'s AD-7 guard. **Must precede step 4** — landing the manifest first, even in the same PR but an earlier commit, leaves a commit range in which the release cut is broken.
4. `contract/step-manifest.yaml`. This is the commit that arms everything.
5. Documentation, including `overseer.md` (orchestrating session).

---

## 4. Answers to the three questions as asked

- **R3 — where does the register live?** `signoffs/<namespace>/step{N}-register.md`, git-committed, per-branch, byte-identical to the ephemeral source, written by a promotion step inside `pr_readiness.py` before the PR opens, verified present **in a commit**, read by both gates through one shared helper, with no legacy fallback. (AD-2, AD-3, AD-4.)
- **Option A or B?** **Option A**, and not as a budget compromise: Option A is the *safer* of the two against R4's own stated failure mode, it copies a cross-clone-proven shipped pattern (#555), it keeps the contract edit additive, and Option B is the only option capable of the partial migration R4 forbids. R4 is superseded (§6).
- **R7 — is activation safe?** Three of the five consumers are unaffected or improved; one (`release_artifact_logic` via `cut_release.sh`) hard-blocks every release and is gated behind an explicit opt-in. Documented, not discovered. (AD-7, ESC-1.)

---

## 5. Escalations

### Bound here, not escalated — with reasons

- **Option A over B** (AD-1): bound technically. The tradeoff the orchestrator described is real, but it does not cut the way the file count suggests — A is safer *and* cheaper, which is rare enough to state explicitly.
- **Per-branch namespacing over flat or per-step** (AD-2): bound, because under AD-5 every PR shares one step id, so a per-step layout collides on nearly every concurrent pair.
- **No `.claudetmp/` fallback** (AD-4): bound, as the stronger reading of R6(c).
- **`DEFAULT_STEP_ID = 1`** (AD-5): bound, because without it R2's fail-closed rule bounces every PR (AF-4).

### ESC-1 — Gating `cut_release.sh`'s sign-off-stamp check is an operational-obligation change. (Product boundary — human.)

Today a release cut performs no sign-off-completeness check (the manifest is absent). After this PR it still performs none, because AD-7 defaults the opt-in to off — but the *reason* changes from "impossible" to "switched off", and turning it on later requires someone to produce `.stamp` files, which is a new per-release manual obligation (`sign_off.sh` is manual and per-role). The alternatives are: (a) AD-7 as bound — ship dark, file a follow-up; (b) accept that every release cut escalates until stamps exist; (c) build a stamp writer now — scope creep, and pm-agent's non-goals bar it. I recommend (a). The human owns the call because it is a change to the release process, not to the code's correctness.

### ESC-2 — Confirm the per-step `required_signoffs`. (Human — pm-agent already flagged this.)

AD-6 proposes `[code-review, test-unit]` on a single step `id: 1`. This is the list every future PR in this repo is gated on, and it is simultaneously the union `signoff_gate.py` and `release_artifact_logic.py` would use if either is ever switched on. The narrow set is a deliberate "make it fire correctly before making it fire loudly" choice; the wider candidate is `[code-review, security, privacy, test-unit, process]`. A human should confirm which, and confirm that a single-step manifest correctly describes how this repo actually builds.

### ESC-3 — The worker-side gate cannot run as documented, and that is a separate defect. (New — mine; AF-5.)

`worker.md:380` omits both `--step` and `--risk-tier`; both are `required=True`. AD-5 defaults `--step`; `--risk-tier` is left alone because defaulting a risk tier inside a gate is exactly the kind of silent softening this system exists to prevent. So after this issue the documented command still exits 2. This needs its own issue — fixing `worker.md`'s invocation line to pass the validated tier — and until it lands, REQ-W-05/06 are not actually running in production either. I am design-only this session and have not filed it; the orchestrating session should. Note the compounding: with AF-1, **both** ends of this gate are currently unexecuted, which is why no one has ever seen F1 or F2 fire.

---

## 6. Startup-gap analysis and affected sign-offs

**Should any of this have been settled before design and code were built against it?** Three items:

- **R4 is superseded by AD-1**, and this is a *reactive ADR revision* in the startup-gap sense: R4 prescribes a mechanism (14-file writer relocation) that AD-1 rules is riskier than the alternative on R4's own stated grounds. pm-agent's requirements document is **PR-stage, with no design and no code built against it** — `technical-design` has not run for #1594 — so **no prior sign-off is orphaned and none requires re-review.** The requirements document should carry a note recording the supersession so a future reader does not implement R4 from the requirements alone. This is a `startup-artifact-gap` candidate only in the weak sense: R3 explicitly deferred the mechanism to the architect, so the process worked as designed.
- **AF-1 (`check_register_completeness()` has no caller) should have been settled at epic-planning time for #1358.** #1594 was scoped and prioritized `priority:critical` on the premise that fixing the function fixes the gate; it does not, without #1357. No sign-off is invalidated (nothing is built), but #1594 and #1357 must be sequenced explicitly on the epic, and #1594's PR body must not claim the gate now fires. Annotate the epic.
- **AD-7 changes an existing shipped control's activation condition** (`cut_release.sh:200`, #695). The control's code and its original sign-off stand; only the trigger changes, and only because a premise that held when it was written (*"a manifest implies stamps exist"*) is false in this repo. **No re-review of #695 is required**, but its tests must be re-run with `HOS_RELEASE_REQUIRE_SIGNOFF_STAMPS` both set and unset, and the #695 rationale comment updated in place so the new condition is legible in the file.

No other prior sign-off is affected: everything else here is new build.

---

## Human Review Required

**RISK: MEDIUM-HIGH.** The change itself is small and copies a proven pattern. The risk is concentrated in two places, both closed positively above rather than cautioned about: (1) creating `contract/step-manifest.yaml` would, unmodified, hard-block every release cut from the moment it merges — found by tracing `cut_release.sh:200` into `release_artifact_logic.py:368-393` and observing that this repository contains zero `.stamp` files (AF-3, closed by AD-7); and (2) R2's fail-closed rule, applied to a repo whose issue-driven worker emits no step id at all, would convert "never bounces" into "always bounces" (AF-4, closed by AD-5's pinned constant). A third route — a promotion that lands in the working tree and never in a commit, and therefore never in the PR — is closed by AD-3's `git cat-file` check rather than by an instruction (AF-2).

**CONFIDENCE: HIGH** on §0; every finding was re-derived from the working tree this session, including the four that extend pm-agent (**AF-1**: the gate has no caller, so this issue cannot make it fire; **AF-3**: only one of R7's five consumers actually flips, and that one blocks releases; **AF-4**: this repo has no step-id domain; **AF-5**: the documented worker-side invocation exits 2 on argparse). **HIGH** on AD-1 through AD-5, which follow from those findings and from a pattern already shipped in this repo. **MEDIUM** on AD-6's specific role list — that is a judgment about how this repo actually builds, which is why it is ESC-2 rather than bound. **LOWER** on anything depending on `post-change-sweep`'s N/A roster, which I could not fully verify and have turned into a verification obligation rather than an assumption.

**BLAST RADIUS:** the overseer's pre-matrix bounce decision and the worker's pre-PR gate — i.e. whether any PR may merge; `contract/OVERSIGHT-CONTRACT.md` and `contract/step-manifest.yaml`, which are protected surfaces and bind every consumer install; `cut_release.sh`'s release path; and a new committed artifact per branch under `signoffs/`. Indirectly #1357 (which must honour AD-5's `configuration_gap` routing) and #1358's sequencing.

**Change classification: STRUCTURAL.** A new committed artifact class, a new bounce reason category, a changed activation condition on a shipped release control, and normative additions to contract text. Per the product-boundary checkpoint, **ESC-1 (operational obligation) and ESC-2 (the gating role set) must be cleared by the human before the corresponding parts bind**; the rest may proceed on `technical-design`'s completion. This PR touches `contract/**` and `.claude/agents/**` and therefore requires human approval regardless of tier — which is the correct place for pm-agent's "Human Review Required" on the contract edit to be satisfied.
