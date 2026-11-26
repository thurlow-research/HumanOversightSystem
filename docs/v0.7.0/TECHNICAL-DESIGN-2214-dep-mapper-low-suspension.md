# TECHNICAL DESIGN — #2214: time-boxed suspension of dep-mapper `Data confidence: LOW` as a blocker

**Status:** ARCHITECT APPROVED WITH CHANGES (round 1 of 5, 2026-11-06). The architect applied the changes directly; they are marked **[ARCH-R1]**. Coding may start. ESC-2 must be answered before the build PR is opened, and only if dep-mapper reports LOW on this step (§11.1).
**Amendment AM-1 (2026-11-18, technical-design; architect review complete — see [ARCH-R3] APPROVED):** §5.3 item 6 changes from a denylist to an allowlist (D-19, D-20). The changes touch §4.2, §4.3 (new V9), §4.5, §5.3, §8 (R-8, R-9), §9 rows 1, 8 and 9, §10 (new group (f)) and §12. They are marked **[AM-1]**. The coder must not implement AM-1 until the architect approves it.
**[ARCH-R2] Architect review of AM-1 (round 2 of 5, 2026-11-18): CHANGES REQUESTED.** The direction (D-19, D-20, D-21, V9) is approved. Findings AR2-1 to AR2-9 are in §12 and must be resolved by technical-design in round 3. Coding of AM-1 stays blocked until then.
**[ARCH-R3] Architect review of AM-1 round 3 (round 3 of 5, 2026-11-18): APPROVED.** AR2-1 to AR2-9 are resolved (§12). The coder may implement AM-1. Security must re-review the build in full.
**[AM-1 R3] Round 3 (2026-11-18, technical-design): AR2-1 to AR2-9 addressed. Architect review complete — see [ARCH-R3] APPROVED.** The response is in §12, "[AM-1 R3] Response to ARCH-R2". The changes are marked **[ARCH-R2 AR2-n]**. Coding of AM-1 stays blocked until the architect approves.
**[AM-2] Amendment AM-2 (2026-11-18, technical-design; architect review complete — see [ARCH-R5] APPROVED):** the default-branch freshness check (§5.2.1) **narrows** R-7 [ARCH-R4 AR4-2]. A window remains between the check and the merge (see R-7). It was triggered by the full-range second review at `54f271235`: codex request_changes, HIGH CWE-362 at `suspension_manager.py:751`. REQ-W-08 blocks on it, and the human chose fix over waive for this pattern (ruling A, 2026-11-13). AM-2 touches D-9, D-16, §5.2, §5.2.1 (new), §5.4, §6, §8 (R-7 narrowed, R-10 new), §9 rows 1–2 and §10 group (g). Round 5 [ARCH-R4] applies AR4-1 to AR4-6. Change class `additive`: it is a tightening, with one new required keyword argument and no loosening. RISK: HIGH (it adds a network dependency to a gate-resolution path). CONFIDENCE: HIGH. BLAST RADIUS: the `--check-suspended-resolutions` (evaluator 7b(iii)) and REQ-W-18 paths only.
**[ARCH-R4] Architect review of AM-2 (round 4 of 5, 2026-11-18): CHANGES REQUESTED.** The approach is approved. Findings AR4-1 to AR4-6 are in §12. Coding of AM-2 stays blocked until they are resolved. AM-1 remains approved and may be coded independently.
**[ARCH-R5] Architect review of AM-2 round 5 (round 5 of 5, 2026-11-18): APPROVED.** AR4-1 to AR4-6 are resolved (§12). The coder may implement AM-2. The loop converged within the cap.
**[AM-2 R5] Round 5 (2026-11-18, technical-design): AR4-1 to AR4-6 addressed. Architect review complete — see [ARCH-R5] APPROVED.** The response is in §12, "[AM-2 R5] Response to ARCH-R4".
**[AM-3] Amendment AM-3 (2026-11-18, technical-design; architect review complete — see [ARCH-AM3] APPROVED):** the disclosure's until-closed value is written as `until-closed: issue N`, not `#N`. It was found at the final submit gate: `scripts/automation/closing_keywords.py` (#1856, run by `bootstrap/submit_pr.sh`) reads `until-closed: #2162` as "closed #2162" and refuses the PR. Declaring it with `--closes 2162` would close #2162 on merge and end the suspension. AM-3 changes §5.3 (template, item 5, item 6 required values, new R8), V9, §9 row 9 and §10 group (h). Change class `clarifying`/`additive`: no rule is loosened, and one rule (R8) is added. RISK: MEDIUM. CONFIDENCE: HIGH. Every form was checked against the real guard. BLAST RADIUS: the disclosure template, `validate_disclosure`, V9, and orchestrator step 1a.
**[ARCH-AM3] Architect review of AM-3 (AM-3 round 1 of 5, 2026-11-18): APPROVED WITH ONE ARCHITECT-APPLIED CHANGE** (§9 row 9, the whole-PR rule). The details and the round-count ruling are in §12. The coder may implement AM-3.
**[AM-4] Amendment AM-4 (2026-11-20, technical-design, #2392; architect review complete — see [ARCH-AM4] APPROVED WITH CHANGES):** S3's manifest flag is now read at pinned SHAs, not from the working tree (§5.2.2, new). The effective flag is the default-branch flag OR the head flag, and the read fails closed when the working-tree manifest differs from the head blob. The trigger was codex HIGH CWE-863 (an uncommitted manifest edit or deletion lowers the gate) and HIGH CWE-807 (a committed branch change lowers it, because unlike the suspension file the manifest was never checked against the default branch). AM-4 touches D-17, §5.2 (signature, S3, the CLI paths line), §5.2.2 (new), §5.4, §8 R-5 (narrowed), §9 rows 1–3, §10 group (i) and §12. Changes are marked **[AM-4]**. Change class `additive`: it is a tightening. It adds one required keyword argument and removes the `manifest_path` parameter of a private function. Nothing is loosened. RISK: HIGH, because it changes the input to the rule that keeps suspension away from human-gated steps (D-7). CONFIDENCE: HIGH on the OR rule and the byte-level consistency check. MEDIUM on D-22, the treatment of a step that is not listed on the default branch, which the architect must rule on. BLAST RADIUS: `--check-suspended-resolutions` (evaluator 7b(iii)) and REQ-W-18. Both are affected only when `suspension_applies` is true, and neither makes a new network call. **The coder must not implement AM-4 until the architect approves it.**
**[ARCH-AM4] Architect review of AM-4 (AM-4 round 1 of 5, 2026-11-20): APPROVED WITH TWO ARCHITECT-APPLIED CHANGES** (AR-AM4-1, AR-AM4-2; marked [ARCH-AM4]) and one disclosed residual (AR-AM4-3). D-22 is approved as refined by AR-AM4-2. AM-4 is a pure tightening once both changes are in. Details in §12. The coder may implement AM-4.
**[AM-4 AL-WD] (2026-11-25, technical-design, #2392): implements human ruling A of 2026-11-24.** The canonical-line allowlist now covers the whole manifest, not only the `steps:` block. An indented first content line, or a U+FEFF anywhere in the text, makes the scan True. Two low agy items are folded in: L1, the intermediate `contract/` path component, and L2, the T-G24 oracle ids. The block is in §5.2.2 after [ARCH-AM4-SR round 5]. Change class `additive` (pure tightening). RISK: HIGH. **Status: [ARCH-AM4-WD] APPROVED with required changes AR-WD-1 and AR-WD-2 (2026-11-25, applied inline). The coder may implement AL-WD.**
**Author:** `technical-design`
**Date:** 2026-11-06
**Issue:** #2214 (milestone v0.7.0). It is a single slice, and the build is 12 files, counting this document (§9).
**Binding input:** the human ruling by ScottThurlow on #2174, 2026-10-30, Q1 B:

> "suspend the dep-mapper LOW finding as blocking until #2162 lands or 2026-12-31, whichever is first; each affected PR keeps dep-mapper's manual trace and discloses LOW in its body; the suspension lands via a PR I approve."

**Also binding:**
- #2170, the human-interface rule. The worker drafts the file and the human approves the PR. The human writes no file.
- #204 / contract §7 condition 7b: an unresolved blocking finding fails compliance.
- The ratchet (`research/findings/ratchet-principle.md`). Only a human may loosen a gate. Automation may only tighten one.

**Out of scope:**
- #2162, the real fix (`docs/v0.7.0/TECHNICAL-DESIGN-2162-S1-dep-trace.md`).
- #2167, a GitHub-approval verifier (v0.7.10).
- Any change to `contract/gate-suspension.template.md`'s general HUMAN ONLY rule. See D-10.

> This document specifies contracts, not code. "Must" is a requirement on the implementation. Decisions are labelled **D-n**. Items that need a human are labelled **ESC-n**.

**Change class:** `additive`. It adds two optional grammar flags, one new resolution form for one kind of blocking finding, two deterministic checks, and one new pre-PR readiness check. The single loosening is the ruling itself, which the human has already authorized. [ARCH-R1] ESC-1 is no longer a loosening in this build: the SPEC-82 WARN is kept unchanged (§6). No existing contract clause is removed.

RISK: HIGH. The design changes when a blocking finding (dep-mapper LOW at HIGH+) stops a PR. It touches protected surfaces (`contract/**`, `.claude/agents/**`) and adds a GitHub read to a gate-suspension path.
CONFIDENCE:
- **HIGH** on the grammar, the status classifier, and fail-closed behaviour. They extend `suspension_manager.py`'s existing idioms (`_SUSPENDED_RE`, and the injectable `today` in `check_grandfathered_until`).
- **MEDIUM** on the trace validator's coverage rule (§4.3). It is structural. It proves a trace exists, covers the diff and claims PASS. It cannot prove the trace is true.
- **HIGH** on §6 [ARCH-R1]. The SPEC-82 WARN is unchanged, which is the non-loosening default. Its cost is operational, not a correctness question.
BLAST RADIUS: every gate that calls `is_suspended` (through `check_suspension.sh` → `--is-suspended`), because the repo now gets a real `contract/gate-suspension.md`. No other gate is listed in it, so for every other gate the result is still "not suspended", with no network call (§3.4). Also affected: every HIGH+ step's risk-assessor, evaluator and `pr_readiness` run while the suspension is active.

## Human Review Required
- **ESC-1 (§6): DEFERRED to a follow-up issue. It does not block this build** [ARCH-R1]. The SPEC-82 authorship WARN stays unchanged. **The consequence you accept by approving this PR:** while `contract/gate-suspension.md` exists, the SPEC-82 check runs on **every** evaluated step in this repo, not only the steps that rely on the suspension. It WARNs on every step, because the last commit touching the file is always a worker-bot squash. So every step is at least CONDITIONAL_PROCEED, and under the overseer's merge matrix (`overseer.md`, the CONDITIONAL/ESCALATE → HUMAN_REQUIRED row) **no PR auto-merges while the file exists** (until 2026-12-31 at the latest, or until a human removes the line). This tightens, so it is the safe default. If you do not want that merge burden, say so on the PR. The relief is the follow-up issue (skip the WARN when the file is identical to the default branch), not a change to this build.
- **ESC-2 (§11.1) [ARCH-R1]: answer before the build PR is opened, and only if dep-mapper reports LOW on #2214's own step.** This step cannot use the suspension it adds (D-16). Does your #2174 Q1 B phrase "the suspension lands via a PR I approve" count as the explicit human instruction (`oversight-orchestrator.md`: "Do not override ESCALATE to PROCEED without explicit human instruction") to open this one PR? It would open with this step's own LOW disclosed, the §4 trace written voluntarily, and the PR human-gated by CODEOWNERS on `contract/**`. **Recommended: A (yes, this PR only).** B (no) means #2214 waits on #2162 like the parked steps, which defeats the ruling.
- **At merge:** the new `contract/gate-suspension.md` (§7) is the suspension. Your CODEOWNER approval of that PR is the authorization (#2170). Check the `SUSPENDED:` line: `expires: 2026-12-31` and `until-closed: #2162`.
- **Disclosed residuals (§8):** R-1 to R-10. R-7 is narrowed by AM-2: the check-to-merge window remains, and is bounded by the SPEC-82 hold (§6). R-10, the network dependency of S4, is new. The PR must disclose both.
- **[AM-1] Disclosure check narrowed after the section, tightened everywhere else (D-19, D-20).** The raw `<` and `]:` bans currently cover the whole PR body. Under AM-1 they cover only the lines **before** the disclosure heading. The disclosure section itself gets a strict allowlist, and nothing after the section is checked. The reason is in D-20: nothing after the section can change how the section renders, because the allowlist bans `[`/`]` (so later definitions have nothing to resolve) and the section ends at an ATX heading. Without the narrowing, the design contradicts itself. The SPEC-82 verification-recipe line that §5.3 requires on every step contains `(#<n>)` and `<default>`, so today REQ-W-18 fails every real disclosure-bearing handoff (`step2214-handoff.md:53` reproduces this). Everywhere else the check gets stricter. Security must re-review AM-1. No human ruling is needed unless you treat narrowing a pre-merge validator's scope as a gate loosening under the ratchet. If you do, say so on the PR.
- **[AM-4] The human gate can no longer be lowered by a branch (#2392, §5.2.2).** Before AM-4, deleting or editing `contract/step-manifest.yaml`, without committing or with a commit on the branch, made a human-gated step eligible for the suspension. After AM-4, a branch can only make the gate stricter. One consequence to notice: any uncommitted change to the manifest now fails REQ-W-18 on a suspension-resolved step, **including a tightening**. The fix is always to commit the change or restore the file. No human ruling is needed. AM-4 only tightens.
- **[AM-4 AL-WD] Whole-document manifest allowlist (your ruling A on #2392, 2026-11-24; §5.2.2).** A consumer manifest that uses a multi-line or block value, a nested block list, deeper than one-level nesting, a bare `: ` value, a non-`[A-Za-z_][A-Za-z0-9_-]*` key, an indented first line or a BOM **anywhere in the file** now counts every step as human-gated for the dep-mapper LOW suspension. That is the safe direction. One refinement of the option text to check: a one-level nested mapping such as the template's `role_mappings:` stays allowed, because otherwise the template could not stay False/False/True (AL-WD-3).

RISK (AM-1): HIGH. AM-1 changes the deterministic check that enforces ruling A on #2214 (the disclosure must be visible text), and it changes the trace contract (V9) that every parked step's re-entry depends on.
CONFIDENCE (AM-1):
- **HIGH** that the allowlist closes every route reported so far: math, rich-render fences (including nested in lists), HTML, comments, definitions, titles, images, reference links, entities, strikethrough, emoji shortcodes and bidi/zero-width characters. Each was prototyped against the grammar in a scratch copy.
- **HIGH** [ARCH-R2] on D-20. The architect confirmed that block parsing only runs forward. P9 (a blank line before the heading) removes the earlier MEDIUM-confidence dependency on ATX-heading interruption. GitHub's renderer is still not available to test against offline.
BLAST RADIUS (AM-1): `validate_disclosure`, `validate_dep_trace` (V9, so the evaluator's S5 too), REQ-W-18, the orchestrator 1a template, the dep-mapper manual-trace template, and every parked step's trace (§4.5).
Change class (AM-1): `additive`. It adds one trace rule and replaces one check's grammar. The signatures, the CLI, the exit codes and the call sites are unchanged.

---

## 0. Search-first findings (verified at `84974bac3`)

Searched `scripts/oversight/`, `scripts/automation/lib/`, `bootstrap/`, `bin/`, `.claude/agents/`, `contract/` and `tests/`.

| Found | Where | What it means for this design |
|---|---|---|
| `_SUSPENDED_RE` accepts only `[pinned]` and `review-by: DATE` | `scripts/oversight/suspension_manager.py:73-76` | If a flag is unknown, the line does not match at all, so the gate is silently not suspended. That is fail-closed, but nothing reports it. `review-by` is only a census nudge. It is not an expiry. |
| `check_grandfathered_until(text, today=None)` | `suspension_manager.py:228` | This is the idiom to copy: lexicographic YYYY-MM-DD comparison with an injectable `today`. Its semantics differ, though. There, a date equal to today counts as expired. See D-2. |
| `cmd_is_suspended(gate)` | `suspension_manager.py:454` | Any matching line means suspended. Called by `check_suspension.sh::is_suspended`, which is already fail-closed on any exit other than 0 or 1. |
| `cmd_auto_remove` | `suspension_manager.py:363` | Only `AUTO_CHECKABLE_GATES` are eligible. `dep-mapper` is not one of them, so the line is never auto-removed. |
| `get_issue(owner, repo, n)` | `scripts/automation/lib/github.py:662` | A retrying REST read, used for the `until-closed` lookup. Returns `None` on 404. Package import: `scripts.automation.lib`. |
| `merge_config.resolve_repo_slug(repo_root)` | `scripts/automation/lib/merge_config.py:117` | Gets owner/repo from `origin`. Raises `ConfigError`. |
| `blocking_findings:` schema | `.claude/agents/risk-assessor.md:226-239` | `resolution: unresolved \| resolved: … \| escalated: <artifact>`. **No deterministic parser exists.** Condition 7b(ii) is evaluator prose only. Only `gate_compliance.py` mentions the field, and only in a message. |
| risk-assessor LOW handling | `risk-assessor.md:130-132` | If `SUSPENDED: dep-mapper` is present, the finding is "limited coverage" and is **not recorded** in `blocking_findings`. The ruling's conditions (trace + disclosure) therefore have no consumer today. |
| `pr_readiness.py` REQ-W-01..W-14 | `scripts/automation/lib/pr_readiness.py:708-751` | The deterministic pre-PR gate (worker.md step 8.9). It already reads `risk-assessment.md` (W-04) and checks that `step{N}-handoff.md` exists (W-14). `handoff.md` **is** the PR body (`oversight-orchestrator.md:94-95`). No REQ-W-18 exists anywhere. |
| SPEC-82 authorship check | `oversight-evaluator.md:547-600` | Takes the last commit touching `contract/gate-suspension.md` and WARNs if its author email is a bot's. On `main`, squash commits are authored by `hos-worker-hos[bot]` (verified: `git log -1 origin/main`), so a worker-drafted file WARNs on **every** step. See §6. |
| Branch protection | `scripts/framework/setup_branch_protection.sh:24,125`; `.github/CODEOWNERS:12` | `require_code_owner_reviews: true`. `/contract/` is owned by `@ScottThurlow`. |
| Consumer ship list | `scripts/framework/framework_consumer_files.txt` | `contract/gate-suspension.md` is not listed, so it stays repo-local. It must not be added. |
| Existing traces | `.claudetmp/oversight/step2171s4-dep-mapper-trace.md` | Close to the §4 convention. §4.5 lists what changes. |
| | `.claudetmp/oversight/step1988-dep-map.md` | This is a dep-mapper **report**, not a manual trace. #1988 must write a new trace. |
| Tests using a suspension file | `tests/oversight/test_scan_gates_empty_args.py:918`, `test_detect_stack.py:214` | Both write it into tmp dirs, so they are unaffected by the real file. |

---

## 1. Overview of the flow

1. risk-assessor (HIGH+) gets `Data confidence: LOW` from dep-mapper.
2. It runs `suspension_manager.py --suspension-status dep-mapper`.
   - `active`, and the effective human gate does not fire: it **records** the finding with `resolution: suspended: dep-mapper (trace: .claudetmp/oversight/step{N}-dep-mapper-trace.md)`. It then asks the session to run dep-mapper in manual-trace mode, and the session writes the output to that path.
   - Any other status, or the effective gate fires: `resolution: unresolved`, as today, with the status named in the description.
3. The evaluator runs `--check-suspended-resolutions` (§5). This re-derives the status, checks the trace, and checks the effective gate. On FAIL → COMPLIANCE FAIL under 7b(ii).
4. The orchestrator writes the disclosure section into `step{N}-handoff.md`, which becomes the PR body (§5.3).
5. `pr_readiness` REQ-W-18 runs the same check, **plus** the disclosure check, before the PR can be opened.

At each of steps 3 and 5, the status is recomputed from scratch. Nothing trusts an earlier step's verdict.

---

## 2. Decisions

| ID | Decision | Reason |
|---|---|---|
| D-1 | **Grammar:** two new optional, order-free flags on a `SUSPENDED:` line: `expires: YYYY-MM-DD` and `until-closed: #<n>`. Each flag may appear at most once. | Extends the existing alternation. A line without the flags parses exactly as before (backward compatible). |
| D-2 | **`expires:` is inclusive.** The suspension is active through `expires` (UTC). It is `expired` when `today_utc > expires`. With the date 2026-12-31, it is active on 2026-12-31 and expired from 2027-01-01T00:00Z. | The ruling says "until … 2026-12-31". The deliberate difference from `grandfathered_until` (where a date equal to today counts as expired) is stated in the docstring and in the contract text. |
| D-3 | **[ARCH-R1, revised] "Lands" is judged from #2162's close history, not its current state.** `expired` if **any** `closed` event in the issue's event history has `state_reason` `completed`, **or** a `state_reason` that is null or absent. It is also `expired` if the issue is currently `closed` with any reason other than `not_planned`. It stays `active` (bounded by the date) only when every past close was `not_planned` and the issue is now `open` or `closed`/`not_planned`. A 404, a truncated event list, or any lookup error → `unknown`. | `not_planned` means the fix did not land, so the date cap governs, as the ruling says. **Reopening must not revive a suspension.** Reopening an issue is a write any agent can make (`edit_issue.sh --state open`). In the round-1 rule, `open (including reopened) → active`, an agent could re-arm an expired suspension, which is an automated loosening and breaks the ratchet. Once the fix lands, the suspension stays ended. An ambiguous close counts as "landed", which is the tightening direction. |
| D-4 | **Fail closed:** only `active` suppresses anything. `absent`, `expired`, `malformed` and `unknown` all mean "not suspended", for every consumer (`cmd_is_suspended`, the evaluator, risk-assessor, REQ-W-18). | Requirement 1. The ratchet. |
| D-5 | **Lookup only when it is needed.** The date is checked first, so an expired date never makes a network call. A gate whose line has no `until-closed:` never makes one. Census never makes one. | This keeps every other gate's `is_suspended` offline and fast. |
| D-6 | **No clock or issue-state override on the CLI.** `today` and `issue_state` can be injected into the pure functions only (tests use in-process calls). `--suspension-status` always reads `contract/gate-suspension.md`, relative to the cwd (repo root), and ignores `--suspension-file`. | An agent could otherwise pass `--today 2026-12-01`, or point at a file it wrote itself. |
| D-7 | **Suspension never resolves a finding behind the effective human gate** (`human_gate_required` OR validated tier CRITICAL). The rule at `oversight-evaluator.md:105` is kept. On those steps the path is still `escalated: .claudetmp/oversight/step{N}-human-authorization.md`. | A human already reviews those steps. There is no reason to weaken the one rule CORE says suspension cannot touch. |
| D-8 | **The `suspended:` resolution is valid only for `source: dep-mapper`.** Any other source using it → FAIL. | The ruling covers dep-mapper LOW only. Without this, the new form would be a generic escape hatch. |
| D-9 | **A resolved-by-suspension finding does not, by itself, force CONDITIONAL_PROCEED.** The conditions are the trace and the disclosure. [ARCH-R1] In practice, every step is CONDITIONAL_PROCEED anyway while the file exists, because of the unchanged SPEC-82 WARN (§6). D-9 is the rule for the mechanism and takes effect once the ESC-1 follow-up lands. [AM-2; ARCH-R4 AR4-2] **Constraint on that follow-up:** it must not remove the human hold on a suspension-resolved step unless the overseer re-runs `--check-suspended-resolutions` (with its §5.2.1 freshness check) against the PR head, immediately before auto-merge, and treats any non-zero exit as HUMAN_REQUIRED. Until then, the SPEC-82 hold is what bounds the R-7 window. | The ruling says the LOW finding stops being blocking. Forcing a human hold *because of the suspension* would undo it. The human still sees the disclosure in every affected PR body. |
| D-10 | **The worker drafts `contract/gate-suspension.md` for this one ruling.** The provenance is in the file's header (§7). The template's general HUMAN ONLY text is **not** changed. | Generalizing "agent drafts, CODEOWNER approves" to every suspension is a structural governance change. It belongs in a follow-up issue that the worker files after merge. |
| D-11 | **The approving PR is cited by reference, not by number.** The file says the approving PR is the merged PR that adds it, with its number on the adding squash commit (`git log --diff-filter=A -- contract/gate-suspension.md`). | The number does not exist when the file is drafted. Filling it in after review would need a post-review commit, a full-range re-review, and a bot commit on the file. |
| D-12 | **The trace's truth is not checked.** It is a structural check (§4.3), and the human reads the trace summary in the PR body. | An honest limit. Proving callers are complete is #2162's job. |
| D-13 | **`reason_category: OTHER`.** | LOW correctly reports a real coverage gap that the manual trace makes up for. It is not "a known non-issue", which is what FALSE_POSITIVE means. |
| D-14 | **Duplicate `SUSPENDED:` lines for one gate → `malformed`.** So is a line that starts `SUSPENDED: <gate>` but fails the strict grammar (an unknown flag, a bad date such as `2026-13-45`, or a repeated flag). | Today such a line is silently ignored. It now gets a named status. It is still not suspended, so this tightens behaviour. No file in this repo has duplicates. |
| D-15 | **[ARCH-R1] A `source: dep-mapper` finding may not use a free-text `resolved:` resolution.** Only `unresolved`, `escalated: <artifact>` or `suspended: …` are allowed. `resolved: …` on a dep-mapper finding → FAIL (S7). | Today 7b(ii) accepts any `resolved: …` text. Without D-15, `resolved: suspended per gate-suspension.md` would skip the trace and disclosure conditions entirely, so "a HIGH step with LOW and no manual trace stays blocked" (#2214) would not hold. A real fix (a stack-specific dep-mapper) makes the finding go away, so it does not need a `resolved:` form. |
| D-16 | **[ARCH-R1] For resolving a blocking finding (S4), the suspension is read from the default branch, not the working tree.** [ARCH-R4 AR4-3] The text is read by `read_default_branch_suspension` (§5.2.1). The default branch and its SHA come from the remote (`git ls-remote --symref --exit-code origin HEAD`). The local `refs/remotes/origin/<D>` must equal that SHA, and `contract/gate-suspension.md` is read at that SHA. The local `origin/HEAD` is not read, and there is no `origin/main` fallback. (This replaces the ARCH-R1 text: `git show <default>:…`, with `<default>` from the local `symbolic-ref` and an `origin/main` fallback.) If the blob does not exist, it differs from the working-tree file, freshness cannot be established (E-F1 to E-F3), or the read fails (E-F4), the result is FAIL ("suspension not on the default branch, or modified on this branch"). The pure function takes the text, and the CLI and REQ-W-18 have no override. `cmd_is_suspended` keeps reading the working tree (backward compatible for consumers' other gates). | The working-tree file can be written by agents. While the SPEC-82 WARN fires on every step (§6), a branch that changes `expires:` produces the **same** WARN as the baseline, so the tamper signal is lost in the noise. Reading what reached the default branch through the CODEOWNER-gated merge gives back a deterministic guard on the one new loosening path. It also means **no step can use a suspension it adds or edits itself**, including #2214's own step (§11.1). |
| D-17 | **[ARCH-R1] Tier and human gate are re-derived, never only passed in.** The effective tier = max(`--tier`/`risk_tier`, `validated_tier:` from `risk-assessment.md`). An absent or unparseable `validated_tier` counts as CRITICAL, so S3 fails. Effective `human_gate_required` = the passed flag OR the manifest's flag for the step (read with the same parser as REQ-W-18, from `contract/step-manifest.yaml`; absent → False). [AM-4] **The manifest's flag is read at pinned SHAs, never from the working tree.** It is the flag in the manifest at the verified default-branch SHA (the `sha` from `read_default_branch_suspension`, §5.2.1) OR the flag at `head_sha`. Absent at a SHA → False. The working-tree manifest must equal the `head_sha` blob byte for byte, where both absent counts as equal. A mismatch, a failed default-branch read or a failed blob read → the step counts as behind the gate, with a named error (§5.2.2). A branch can make the gate stricter, never looser. | The caller (the evaluator, an LLM; or the worker's `--risk-tier` on `pr_readiness`) supplies these values. A caller that passes `--tier HIGH` on a CRITICAL step must not be able to clear S3. This is the effective-human-gate rule (`oversight-evaluator.md` "Effective human gate (re-derived, not trusted …)") applied to the new path. |
| D-18 | **[ARCH-R1] The parser cannot fail open.** The CLI counts raw lines in `risk-assessment.md` matching `^\s*resolution:\s*suspended:` and compares the count with the parsed findings that have a `suspended:` resolution. A mismatch → FAIL (S0). `applies` is true if either count is non-zero, or if any parsed finding has `source: dep-mapper`. The header `base_sha`/`head_sha` must equal `--range`, else FAIL. | A hand-rolled block parser that misses an entry would report `applies=False`, which is PASS. The cross-check turns a parser miss into a FAIL. The range check stops a stale assessment from another step from being used, even when the CLI is run on its own, outside REQ-W-04. |
| D-19 | **[AM-1] The disclosure section is checked against an allowlist, not a denylist.** Every raw line from the disclosure heading to the end of its section must match the line grammar in §5.3 item 6 (R0–R7). The grammar uses a closed character set and closed line shapes, so any construct not listed is rejected. | Security found five bypasses in a row: link-reference definitions, a comment opener inside a code span, multi-line link titles, GitHub math, and rich-render fences nested in list items. Each was patched with one more denylist rule. Every GitHub render extension is a new way to hide text, so a denylist cannot converge. An allowlist bounds the residual to inline syntax built from the allowed characters (R-8). Rendering through the GitHub markdown API was the other option. It was rejected for two reasons. First, GitHub renders math and mermaid in the browser, after the markdown API has returned its HTML, so a render-API check would not have caught the `$$\color{white}` route either [ARCH-R2]. Second, REQ-W-18 would need the network, and REQ-W-18 must stay deterministic and offline. |
| D-20 | **[AM-1] Outside the section, only the lines *before* the heading are checked, and only for constructs that can swallow a later heading. Lines after the section are not checked.** The orchestrator places the section directly after the AI-Submitted block, so the checked prefix is that fixed template. [ARCH-R2 AR2-1] That premise is enforced, not assumed: P7 requires line 1 to be the AI-Submitted heading, P8 allows no other heading in the prefix, and P9 requires a blank line directly before the disclosure heading. | P9 means nothing in the prefix needs an ATX heading to interrupt it. Paragraphs, tables, list items, blockquotes and multi-line link titles all end at a blank line. Only an open fenced block, a math block or an HTML block can carry across a blank line, and P1–P3 ban the openers of all three. Content after the section cannot change how the section renders. CommonMark/GFM block parsing runs forward only. The section's last line is blank when a heading follows it (R7). The section contains no `[`/`]`, so later link-reference or footnote definitions have nothing to resolve. The one exception is the Kind C attribution literal [ARCH-R2 AR2-9]. It is a complete inline link `[text](url)`, not a reference link, so no definition can redirect it. A body-wide scan adds no safety. It also caused false positives: 4 of the 61 existing handoffs, and the §5.3 SPEC-82 recipe line on every step. |
| D-21 | **[AM-1] Copy invariant.** Suppose a trace passes V1–V9, the suspension's `Authorized by:` value passes R1 and R4 [ARCH-R2 AR2-8], the handoff's line 1 is the AI-Submitted heading, and the orchestrator fills the §5.3 template exactly, copying the two trace sections unchanged and placing the section per D-20. Then `validate_disclosure` passes. A test pins this (T-D1). | A disclosure failure should always mean someone deviated from the template, never that a faithful copy was rejected. V9 moves every content failure back to trace time. |
| D-22 | **[AM-4] A step that the default-branch manifest does not list contributes False, not True.** The head read keeps the existing strict rule: a manifest that exists but does not list the step → True. All other fail-closed parser outcomes stay True on both reads: anchors, merge keys, flow style, a garbage value, a missing `steps:` block, or an undecodable file. [ARCH-AM4] **Ruled: approved, refined by AR-AM4-2.** On the default read, "not listed" gives False only when the default text is canonical for this step: no raw occurrence of the step id and every parsed item id is a plain scalar (§5.2.2 item 2). Otherwise True. "No `steps:` block" is not "not listed" (AR-AM4-1). | A step's manifest entry is normally added on the step's own branch. Under the strict rule, every new step would be human-gated by the default-branch read alone, so the suspension could never apply to it. That would quietly override the human's #2174 ruling. "Not listed on the default branch" is not a loosening relative to today's behaviour. Today only the working tree is read, and the head read (equal to the working tree after the consistency check) still applies the strict rule to that step. If the default branch lists the step as gated, it stays gated whatever the branch does. |

---

## 3. `suspension_manager.py` — grammar and status classifier

### 3.1 Grammar

- `_SUSPENDED_RE`'s flags alternation gains `\s+expires:\s*\d{4}-\d{2}-\d{2}` and `\s+until-closed:\s*#\d+`.
- A new loose matcher, `_SUSPENDED_LOOSE_RE = ^SUSPENDED:\s*(?P<gate>[a-z0-9-]+)(\s|$)`, finds lines that name a gate but fail the strict grammar.
- `Suspension` gains `expires: str | None`, `until_closed: int | None` and `malformed: bool`.
- `parse_suspensions(text)` keeps its signature and its comment handling. It returns every strict-matching line, as before. A strict match with a repeated flag, or an `expires` that fails `datetime.strptime(..., "%Y-%m-%d")`, is returned with `malformed=True`.
- Loose-only lines are **not** returned by `parse_suspensions`, which stays backward compatible. They are seen by `suspension_status` instead (§3.2).

### 3.2 `suspension_status(text, gate, today=None, issue_state=None) -> dict`

This is a pure function. `today` defaults to `_today()` (UTC). [ARCH-R1] `issue_state` is `Callable[[int], tuple[str, str | None, list[str | None]]]` and defaults to `_default_issue_state`. It returns `(current_state, current_state_reason, past_close_reasons)`. `past_close_reasons` holds the `state_reason` of every `closed` event, using `None` where the field is null or absent. The function returns `{status, gate, expires, until_closed, detail}`. The rules are applied in this order, and the first match wins:

1. No line strict- or loose-matches `gate` → `absent`.
2. More than one such line, any loose-only line, or `malformed=True` → `malformed`.
3. `expires` is set and `today > expires` → `expired` (`detail: "expired <expires+1 day>"`). **`issue_state` must not be called.**
4. `until_closed` is set. Call `issue_state(n)`. Any exception, or a return value of the wrong shape → `unknown`.
   - Any entry of `past_close_reasons` is not `"not_planned"` (that is, `"completed"`, `None`, or anything else) → `expired` (`detail: "#<n> closed (<reason>) — landed"`). This holds even if the issue is open now (D-3: reopening does not revive the suspension).
   - Current state `"closed"` with a reason other than `"not_planned"` → `expired`.
   - Current state `"open"`, or `"closed"` with `"not_planned"` → continue to step 5.
   - Any other current state → `unknown`.
5. → `active`.

### 3.3 `_default_issue_state(n)`

This is a lazy import, so the module's import stays stdlib-only. It inserts the repo root (`Path(__file__).resolve().parents[2]`) into `sys.path` and imports `scripts.automation.lib.github` and `merge_config`. It resolves the slug from `origin`, calls `github.get_issue`, and [ARCH-R1] calls `github.list_issue_events` (paginated; it raises rather than truncate, #2209). It returns `(issue["state"], issue.get("state_reason"), [e.get("state_reason") for e in events if e.get("event") == "closed"])`. A `None` issue, an import failure, a `ConfigError`, a `GitHubError` or `ListTruncatedError`, or a missing key all raise, which gives `unknown`.

### 3.4 Changes to existing consumers

- `cmd_is_suspended(gate)` → exit 0 **iff** `suspension_status(...).status == "active"`, else 1. A gate with no `until-closed` makes no network call (D-5).
- `cmd_census` prints each line's status, using a date-only computation. For an `until-closed` line it appends `(until-closed #<n>: not checked by census)`. A line whose date has expired is flagged `EXPIRED — no longer suppressing; remove this line`, and a loose-only line is flagged `MALFORMED — not suppressing`. Census counts only lines that are not expired and not malformed. It never makes a network call.
- `cmd_auto_remove` / `cmd_check`: unchanged. `dep-mapper` is not auto-checkable, and a test pins this (T-C10).

### 3.5 CLI `--suspension-status GATE`

This prints `STATUS=<s>`, `GATE=<g>`, `EXPIRES=<d|>`, `UNTIL_CLOSED=<n|>` and `DETAIL=<text>`, one per line, on stdout.

| Status | Exit |
|---|---|
| `active` | 0 |
| `absent` | 1 |
| usage error | 2 |
| `expired` | 3 |
| `malformed` | 4 |
| `unknown` | 5 |

Callers treat any non-zero exit as not suspended. There is no `--today` flag (D-6).

---

## 4. The manual-trace artifact

### 4.1 Path

The path is exactly `.claudetmp/oversight/step{N}-dep-mapper-trace.md`. `{N}` is the same step-id string the sign-off register uses (for example `2171s4`). `dep_trace_path(step) -> str` is the single source for the path.

### 4.2 Required content

```markdown
# dep-mapper manual trace — step {N}

Range: {BASE_SHA}..{HEAD_SHA}
dep-mapper result: Data confidence: LOW (<free text>)
Date: YYYY-MM-DD

## Callers / readers checked

| Changed file | Callers / readers | Check | Result |
|---|---|---|---|
| path/one | ... | ... | pass |

## Items dep-mapper left untraced

- <each wiring item dep-mapper's LOW report listed, and how it was checked> (or "- none")

## Conclusion

Result: PASS
<free text>
```

[AM-1] The `## Callers / readers checked` and `## Items dep-mapper left untraced` sections are copied into the PR body unchanged (§5.3), so they must use the disclosure line grammar (§5.3 item 6, R1–R5). In those two sections:
- the section headings are at column 0, with at most trailing spaces (an indented or tab-trailed heading is not found, so V4 or V7 fails);
- no backticks, `$`, `\`, `&`, `[`, `]`, `<`, `>`, `*`, `~`, tabs or non-ASCII characters other than `—`, `–`, `→`, `§`;
- no `**bold**`;
- write "about line 1921", not `~1921`;
- write "double-pipe true", not `|| true`;
- write "the token :http-N", not `` `:http-<n>` ``.

The header, `Range:`, `dep-mapper result:`, `Date:` and `## Conclusion` lines are not copied, so they are not restricted.

### 4.3 `validate_dep_trace(text, step, base_sha, head_sha, changed_files) -> {valid, errors}`

This is a pure function. Every rule is checked and every error is collected. It does not stop at the first failure.

- **V1.** The first non-blank line matches `^# dep-mapper manual trace [—-] step (\S+)\s*$`, and the captured step equals `step`.
- **V2.** A line `Range: <x>` exists, and `x == f"{base_sha}..{head_sha}"` exactly (full SHAs). This makes a trace from before re-entry stale.
- **V3.** A line starting `dep-mapper result:` exists and contains `Data confidence: LOW`.
- **V4.** A `## Callers / readers checked` section contains a markdown table. Its header's first cell is `Changed file` and its last cell is `Result`, and it has at least one data row.
- **V5. Coverage.** Every path in `changed_files`, except those under `tests/` or `audit/`, appears in some row's first cell. Matching is done after backticks are removed, and the path must be bounded on the left by the cell start, whitespace, `,` or `(`, and on the right by the cell end, whitespace, `,` or `)`, so `foo (path/to/file.py)` matches. Deleted files are included.
- **V6.** Each data row's last cell, lowercased, starts with `pass`, `no impact` or `n/a`. A cell starting with `fail` gives the error "trace reports a failing caller". Anything else gives "unrecognised result".
- **V7.** A `## Items dep-mapper left untraced` section exists and has at least one non-blank line.
- **V8.** A `## Conclusion` section contains a line matching `^Result:\s*PASS\s*$`.
- **V9 [AM-1].** The lines of the `## Callers / readers checked` section and the `## Items dep-mapper left untraced` section each satisfy the disclosure line rules R1–R5 (§5.3 item 6), applied to the section's lines as if they were the disclosure section. R5 applies in full, so the trace table needs the GFM delimiter row too. [ARCH-R2] V9 also has these rules:
  - **(AR2-5)** The trace section's own heading line counts as Kind B for R5(d), so a table on the line directly after `## Callers / readers checked` has a valid "line before". The disclosure treats the same copied heading as Kind B, so the copied table passes R5(d) there too.
  - **(AR2-4)** The `## Items dep-mapper left untraced` section must contain **no** Kind D line (a line starting `|`). Error: `V9: ## Items dep-mapper left untraced line <k>: table rows are not allowed here (the disclosure carries one table, the callers table)`. With this rule, the only table that can be copied into the disclosure is the callers table, and D-21 holds.
  - **(AM-3)** R8 applies to each of the two trace sections, so a trace whose untraced items say `fixes #123` fails at trace time (D-21). The error is `V9: <section heading> line <k>: <R8 message>`.
  - **(AR2-9)** `validate_dep_trace` splits the trace text as R0 specifies (on `\n` only) for **every** V-rule, V1–V9, so all line numbers agree.

  The error is `V9: <section heading> line <k>: <the R-rule message>`, where `<k>` is the 1-based line number in the trace file. V9 is what makes the D-21 invariant hold: a valid trace whose two sections are copied unchanged into the §5.3 template always passes P0–P5, P7–P9 and R0–R7. It also surfaces the problem at evaluator time (S5), not at PR time.

### 4.4 CLI `--validate-dep-trace STEP --range BASE..HEAD`

This reads `dep_trace_path(STEP)`. There is no path override. `changed_files` comes from `git diff --name-only BASE..HEAD`. It prints `TRACE=valid|invalid|absent` and one `ERROR=` line per error.

| Result | Exit |
|---|---|
| valid | 0 |
| absent | 1 |
| usage error or `git` failure (fails closed) | 2 |
| invalid | 4 |

### 4.5 What existing traces need

- **`step2171s4-dep-mapper-trace.md`**
  - Add `Result: PASS` under `## Conclusion`.
  - Split the row `bootstrap/worker-cron-prompt.md, overseer-cron-prompt.md` so it names `bootstrap/overseer-cron-prompt.md` in full.
  - Make sure every non-test changed file has a row.
  - Regenerate `Range:` for the re-entry range.
  - [AM-1] V9: rows 5 and 6 use `~`. All three untraced items use `**bold**` and backticks.
- [AM-1] **`step2255-dep-mapper-trace.md`** fails V9: one row has backticks, `*`, `<` and `>`. The untraced items have `**bold**`, backticks, `|| true`, and a continuation line starting `/`. That last one is allowed, because R3 permits `/`.
- [AM-1] **`step2214-dep-mapper-trace.md`** (this step, §11.1) fails V9: row 9 has backticks and row 12 has `~`. It must be rewritten anyway, because `Range:` is stale.
- **`step1988-dep-map.md`** is a report. #1988 must write `step1988-dep-mapper-trace.md` from scratch.
- **Every other parked step** must write the trace at re-entry, because its range changes when it merges from `main`.

---

## 5. Resolving the blocking finding

### 5.1 Resolution grammar

The new form for `resolution:` is:

```
resolution: suspended: dep-mapper (trace: .claudetmp/oversight/step{N}-dep-mapper-trace.md)
```

It matches `^suspended:\s*(?P<gate>[a-z0-9-]+)\s*\(trace:\s*(?P<path>\S+)\)\s*$`. Before matching, an inline `# comment` that is preceded by whitespace is removed.

### 5.2 `parse_blocking_findings(text)` and `check_suspended_resolutions(...)`

These live in `suspension_manager.py`.

**`parse_blocking_findings(text) -> list[dict]`**
- It reads the block after `blocking_findings:`. `[]` means empty.
- A `- id:` line starts an entry. Indented `key: value` lines fill it in (`id`, `source`, `description`, `resolution`).
- The block ends at the first non-blank line that is not indented and is not a list item.

**`check_suspended_resolutions(risk_text, step, base_sha, head_sha, tier, human_gate_required, changed_files, main_suspension_text, worktree_suspension_text, handoff_text=None, require_disclosure=False, today=None, issue_state=None, read_text=<fs reader>) -> {applies, ok, findings: [{id, ok, errors}]}`** [ARCH-R1: the two suspension-text parameters were added for D-16]

[AM-4] It gains a second required keyword-only argument, `human_gate_error: str | None`, next to `main_suspension_error`. There is no default, so a caller cannot skip the pinned read (T-G9). `human_gate_required` is now the caller's floor OR `effective_manifest_human_gate(...)["flag"]` (§5.2.2). The function itself never reads the manifest.

- `applies` is True iff at least one finding has a `suspended:` resolution, any finding has `source: dep-mapper`, or the raw count in S0 is non-zero (D-18).
- **S0 (whole file) [ARCH-R1].** The raw `resolution:\s*suspended:` line count equals the parsed count, and the header `base_sha`/`head_sha` equal the range (D-18). Otherwise `ok=False`.
- **Effective tier and human gate [ARCH-R1]** are computed once, before S3, as D-17 specifies: the `tier` argument max'd with the header's `validated_tier:` (absent or unparseable → CRITICAL), and the flag OR'd with the manifest.
- `ok` is True iff S0 passes, S7 passes, and every `suspended:` finding passes **all** of the following:
  - **S1.** `source == "dep-mapper"` and gate `== "dep-mapper"` (D-8).
  - **S2.** `path == dep_trace_path(step)`.
  - **S3.** Not behind the effective human gate. Fail if the effective tier is CRITICAL or the effective `human_gate_required` is true (D-7, D-17). [AM-4] If `human_gate_error` is not `None`, S3 fails with that message alone, in place of `S3: step is behind the human gate (…)`. The step counts as behind the gate whatever `human_gate_required` says. This mirrors S4's `main_suspension_error` substitution.
  - **S4.** [ARCH-R1] `main_suspension_text` is not `None` and equals `worktree_suspension_text` byte for byte (D-16), **and** `suspension_status(main_suspension_text, "dep-mapper", …)` is `active`, recomputed here (D-4). [AM-2] If `main_suspension_error` is not `None`, S4 fails with that message alone, in place of "suspension not on the default branch". The freshness check that produces this message is in §5.2.1.
  - **S5.** `validate_dep_trace` is valid. An absent file fails.
  - **S6.** Only when `require_disclosure`: `validate_disclosure(handoff_text, step, trace_text, suspension_text)` passes (§5.3; #2349). An absent `handoff_text` fails.
- **S7 [ARCH-R1].** No `source: dep-mapper` finding has a `resolved: …` resolution (D-15).
- Findings with `unresolved` or `escalated:` resolutions are left to the existing 7b(ii) rules and are not counted here.

#### 5.2.1 [AM-2] Default-branch freshness (narrows R-7; codex CWE-362 at `suspension_manager.py:751`, head `54f271235`)

**Problem.** S4 reads the suspension from the local `refs/remotes/origin/<default>`. Suppose a human revokes the suspension on the default branch, by removing the `SUSPENDED:` line or deleting the file, and this clone has not fetched since. Then the stale local blob still equals the worktree copy, and S4 accepts a revoked authorization. The human chose fix over waive for this pattern (ruling A, 2026-11-13).

**Contract.** `read_default_branch_blob(path, repo_root)` is replaced by:

`read_default_branch_suspension(repo_root=".", ls_remote=None) -> {"text": str | None, "error": str | None, "sha": str | None, "branch": str | None}`

It is a single read path, done in four steps. [ARCH-R4 AR4-1] The default branch and its SHA both come from the **remote**, in one call. No local `refs/remotes/origin/HEAD` is read, and there is no `main` fallback on this path. An agent can repoint the local `origin/HEAD` with one `git symbolic-ref` command, so it is not trusted (T-F10).
1. **Remote default branch and SHA.** `ls_remote(repo_root)` returns `(D, sha, None)` or `(None, None, reason)`. The production default is `_default_ls_remote`. It runs `_git(["ls-remote", "--symref", "--exit-code", "origin", "HEAD"], repo_root, env={"GIT_TERMINAL_PROMPT": "0"})` through the existing bounded `_git` helper, with its 60 s timeout. `_git` gains one optional `env` overlay argument, which is merged over `os.environ` and used only here.

   Parsing: split stdout on `\n`, and drop one trailing `\r` per line. [ARCH-R4 AR4-4] `ls-remote` patterns match the *end* of a ref name, so a pushed `x/HEAD` adds lines. Select lines only by an **exact** second field. A line is used only if its tab-separated second field **equals** `HEAD`, and every other line is ignored.
   - The **symref line** is a used line whose first field matches `^ref: refs/heads/(?P<D>[^\t]+)$`.
   - The **SHA line** is a used line whose first field matches `^([0-9a-f]{40}|[0-9a-f]{64})$`.

   Each must appear **exactly once**. `<D>` must match `^[A-Za-z0-9._/-]+$`, must not start with `-`, and must not contain `..`. Every regex built from `<D>` elsewhere uses `re.escape(D)`.

   The reason strings, any of which gives the error **E-F2**, are:
   - `_git` returns `None` (timeout or `OSError`) → `git ls-remote did not complete within 60s or could not be started`.
   - exit code 2 → `origin reports no HEAD`.
   - any other non-zero exit → `exit <rc>: <first non-empty stderr line, at most 200 chars>`.
   - no symref line → `origin did not report its default branch (no "ref: refs/heads/... HEAD" line)`.
   - more than one symref line, or more than one SHA line, or no SHA line → `ambiguous or incomplete ls-remote output for HEAD`.
   - `<D>` invalid → `unusable default-branch name from origin`.
2. **Local SHA.** `_git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{D}^{{commit}}"])`, where `<D>` is the remote's name. A failure, or output that is not a 40- or 64-hex SHA, gives the error **E-F3**.
3. **Compare.** If the remote SHA is not the local SHA, return the error **E-F1**. This also catches a local ref that is *ahead* of origin, for example after a force-push on origin.
4. **Read.** Only on a match, read the fixed **`SUSPENSION_FILE`** (`contract/gate-suspension.md`) at the verified SHA. The reader takes no path parameter [ARCH-R4 AR4-3]. Reading by SHA, not by ref name, leaves no window between the check and the read. [ARCH-R4 AR4-5] Existence and read are separated:
   - `_git(["ls-tree", "-z", sha, "--", SUSPENSION_FILE])` with exit 0 and **empty** output means the path does not exist at that commit. The reader returns `text=None, error=None`, so the existing S4 "suspension not on the default branch" message applies (D-16).
   - Exit 0 with one `100644 blob <oid>\t<SUSPENSION_FILE>` entry means the path is present. Then `_git(["show", f"{sha}:{SUSPENSION_FILE}"])` gives the text.
   - Anything else gives the error **E-F4**: `ls-tree` or `show` returning `None` (timeout), a non-zero exit, or an entry that is not a regular blob (for example a symlink, mode `120000`, or a tree).

On every error path, `text` is `None`. On success, `sha` is the verified SHA, and the returned dict also carries `"branch": D`.

**Error messages** (printed by the CLI as `ERROR=<id>: S4: …` on each `suspended:` finding):
- **E-F1 (stale):** `S4: local origin/<D> is <local[:12]> but origin has <remote[:12]>; the default-branch suspension may have been revoked or changed. Run 'git fetch origin' and re-run`.
- **E-F2 (lookup failed):** `S4: could not confirm origin/<D> is current (<reason>); failing closed. Check network access and the GitHub token, then re-run`.
- **E-F3 (no local ref):** `S4: local ref origin/<D> not found; run 'git fetch origin' and re-run`.
- **E-F4 (read failed) [ARCH-R4 AR4-5]:** `S4: could not read contract/gate-suspension.md at origin/<D> <sha[:12]> (<reason>); failing closed, re-run`. Here `<reason>` is `timeout`, `exit <rc>: <stderr line>` or `not a regular file`.

In E-F1 and E-F3, `<D>` is the remote's default-branch name. In E-F2, before the name is known, `origin/<D>` is written as `origin/HEAD`.

**Signature change.** `check_suspended_resolutions` gains the **keyword-only, required** argument `main_suspension_error: str | None`, with no default. Every caller must pass the reader's `error` along with its `text`. A call site that forgets cannot silently skip freshness, because the call raises `TypeError`, which fails closed. The pure function stays pure: it never makes the network call itself. Unit tests that do not test freshness pass `main_suspension_error=None`.

**When the network call happens.** It happens only on the two paths below, only once per invocation, and only when `suspension_applies(risk_text)` is true: both callers guard the reader with it, so a step with no suspension makes no network call (pinned by a test).

**Replace refs.** `_git` always sets `GIT_NO_REPLACE_OBJECTS=1` in the child environment, merged with any `env` overlay. Otherwise an author could create `refs/replace/<real_main_sha>` pointing at a forged commit: `rev-parse` still returns the real SHA, so the compare passes, but `ls-tree` and `show` read the forged tree. The same applies to `git diff` in `changed_files_in_range` (V5).

**Affected callers:**
- `--check-suspended-resolutions` (`cmd_check_suspended_resolutions`): the evaluator's 7b(iii) path and standalone runs. It uses `read_default_branch_suspension()` and passes `text` and `error`.
- `pr_readiness` REQ-W-18 (`_check_dep_mapper_suspension`): it uses `read_default_branch_suspension(repo_root)` and passes `text` and `error`. [ARCH-R1 rule extended] It must not pass `ls_remote`. T-A4 is extended to pin this.

**Unchanged:** `--is-suspended` (`cmd_is_suspended`), `--suspension-status`, `check_suspension.sh` / `run_gates.sh`, census, `--check` and `--auto-remove`. All of them read only the **working-tree** `contract/gate-suspension.md` and never the origin ref, so they are not exposed to this stale-ref race. I checked `cmd_is_suspended`, `cmd_suspension_status` and `scripts/oversight/gates/check_suspension.sh` at `54f271235`. Their worktree read can be stale in a different way, which is already covered: a suspension of `dep-mapper` that only the worktree shows never resolves a blocking finding without S4 (D-16). No other gate is listed in the file (§3.4).

**CLI** `--check-suspended-resolutions STEP --range BASE..HEAD --tier T --human-gate-required true|false [--require-disclosure]`
- `--tier` and `--human-gate-required` are required, so leaving them out is a usage error with exit 2. Nobody can pass by omission. [ARCH-R1] Neither value can *lower* the result. Both are floors (D-17).
- It reads fixed paths only: `.claudetmp/oversight/validators/risk-assessment.md`, `dep_trace_path(STEP)`, `.claudetmp/oversight/step{STEP}-handoff.md`, `contract/gate-suspension.md` (working tree), `git show <default>:contract/gate-suspension.md` (D-16; [AM-2] read at the SHA verified against `git ls-remote origin`, §5.2.1) and `contract/step-manifest.yaml` (D-17). [AM-4] The manifest is no longer read as a working-tree file for S3. The CLI reads it at the verified default-branch SHA and at HEAD from `--range BASE..HEAD`, and it compares the working-tree bytes of `contract/step-manifest.yaml` (cwd-relative) with the HEAD blob (§5.2.2). It does so only when `suspension_applies(risk_text)` is true, in the same guarded branch as `read_default_branch_suspension()`. `--human-gate-required` stays required and stays a floor: the value passed is `(flag == "true") or eff["flag"]`, together with `human_gate_error=eff["error"]`. When no suspension applies, the CLI passes `human_gate_required=(flag == "true")` and `human_gate_error=None`, and makes no git manifest read, because `check_suspended_resolutions` then returns `applies=False` without reaching S3. There is no flag that overrides any of these paths, the date, the issue state, or the remote lookup.
- Output is `APPLIES=yes|no`, `RESULT=ok|fail`, and one `ERROR=<id>: <msg>` line per error.

| Result | Exit |
|---|---|
| ok, or not applicable | 0 |
| usage error, git failure, or risk-assessment.md missing | 2 |
| fail | 4 |

#### 5.2.2 [AM-4] The SHA-pinned human gate (#2392; codex HIGH CWE-863 and CWE-807)

**Problem.** `manifest_human_gate_required(path, step)` reads `contract/step-manifest.yaml` from the working tree, and an absent file gives False. An uncommitted edit or deletion therefore flips a human-gated step to not gated (CWE-863). A branch can also commit `human_gate_required: false`. D-16 pins the suspension file to the default branch, but the manifest was never pinned (CWE-807). Either way, S3 lets the suspension resolve a finding on a step that D-7 forbids.

**Contract.** All of this lives in `suspension_manager.py`. The fixed path is `_STEP_MANIFEST_PATH = "contract/step-manifest.yaml"`. No caller can pass a different path.

1. **Parser refactor.** The line-scan body of `manifest_human_gate_required` moves, unchanged, into `_manifest_gate_scan(text: str, step) -> bool | None`. The return value is `None` only where the current code returns True because no item has `id == step` (the `if not target: return True` branch). Every other outcome is unchanged. `manifest_human_gate_required(manifest_path, step) -> bool` keeps its signature and behaviour:
   - path absent → False;
   - `OSError` or `UnicodeDecodeError` on read → True;
   - otherwise `_manifest_gate_scan(...)`, with `None` mapped to True.

   Every existing `test_manifest_*` test must pass unchanged (T-G10).

   [ARCH-AM4 AR-AM4-1] `None` means **a `steps:` block was found and no item has `id == step`**. If no line ever matched `steps:` (absent block, or an indented `  steps:` that the scanner does not enter), the scan returns True, not `None`. The current code does not separate the two cases (both reach `if not target`), so the refactor must track whether `in_steps` was ever set. Without this, D-22 would turn "no `steps:` block" into False on the default read, contradicting D-22's own text and T-G8.
2. **`read_manifest_gate_at(sha: str, step, repo_root=".", *, unlisted_step: bool) -> {"flag": bool, "blob": bytes | None, "error": str | None}`.** It reuses the read pattern of `read_default_branch_suspension` (§5.2.1), through `_git`, so the call is bounded at 60 s and runs with `GIT_NO_REPLACE_OBJECTS=1`:
   - `sha` must be a full SHA (`_HEX_SHA_RE`). Anything else → `error`. This also refuses an option-shaped value.
   - Run `ls-tree -z <sha> -- contract/step-manifest.yaml`. No entry → `{"flag": False, "blob": None, "error": None}`, because the file is absent at that SHA (D-17).
   - The single entry must fullmatch `100644 blob <hex>\tcontract/step-manifest.yaml`. Any other entry (a symlink, `100755`, a tree, a submodule, more than one entry) → `error` `not a regular file`.
   - Run `show <sha>:contract/step-manifest.yaml`. Keep the raw stdout bytes as `blob`.
   - Decode the bytes as strict UTF-8. On failure → `flag=True`, `error=None`, as the path function does.
   - Otherwise take `_manifest_gate_scan(text, step)`. `None` → `unlisted_step`.
   - [ARCH-AM4 AR-AM4-2] **When `unlisted_step` is False (the default read), `None` gives False only if both hold; otherwise True:** (a) the decoded text, comments included, contains no match of `(?<![A-Za-z0-9._/-])` + `re.escape(str(step))` + `(?![A-Za-z0-9._/-])`; and (b) every parsed item's `id` value fullmatches `[A-Za-z0-9._/-]+`. Reason: the line scanner was built to be safe only because "not found" meant True. D-22 removes that backstop on the default read, so a gated entry the scanner fails to see would contribute False, and a branch could then rewrite that entry canonically with `false` and lower the gate with a committed change. Reproduced at `99e40eea0`: `id: >-` with `s1` on the next line (valid YAML, a real parser reads `id: s1`) scans as not listed; so do an indented `  steps:` block and a tab-indented item. (a) catches block scalars, duplicate `id:` keys (scanner keeps the first, YAML the last), tags (`!!str s1`) and unseen items; (b) catches escapes (`"s\x31"`) and block-scalar indicators. A false positive (the id appears in a comment or another field) gates the step, which is the safe direction; the fix is a human edit to the default-branch manifest.
   - `_git` returning `None` → `timeout`. A non-zero exit → `exit N: <_stderr_line>`.
   - On every error path, `flag=True` (fail closed).

   The coder may extract the shared ls-tree/show steps into a private helper that both readers use, provided T-F12's messages for the suspension file stay byte-identical.
3. **`effective_manifest_human_gate(step, head_sha: str, default_read: dict, repo_root=".") -> {"flag": bool, "error": str | None}`.** `default_read` is the dict that `read_default_branch_suspension` returned to the same caller. It is not re-read, so there is no second `ls-remote` call, and the manifest is read at exactly the SHA the suspension was read at. The steps run in this order, and the first error returns `{"flag": True, "error": <message>}`:
   - **G1.** `default_read["error"]` is not `None`, or `default_read["sha"]` is not a full SHA → E-G1.
   - **G2.** `head_sha` is not a full SHA → E-G4.
   - **G3.** `head = read_manifest_gate_at(head_sha, step, repo_root, unlisted_step=True)`. An error → E-G3, with `where="head"`.
   - **G4 (working-tree consistency).** `os.lstat(repo_root / "contract/step-manifest.yaml")`:
     - `FileNotFoundError` → absent;
     - not `S_ISREG` (a symlink, a directory, a FIFO) → E-G2 `not a regular file`;
     - otherwise read the bytes; an `OSError` → E-G2 `unreadable: <strerror>`.

     Compare with `head["blob"]`. Both absent → consistent. Present at head but absent in the working tree → E-G2 `deleted`. Absent at head but present → E-G2 `added but not committed`. Both present and the bytes differ → E-G2 `modified`. The comparison is raw bytes, with no decoding and no newline normalisation, and it does not consider direction: an uncommitted tightening fails too.
   - **G5.** `default = read_manifest_gate_at(default_read["sha"], step, repo_root, unlisted_step=False)` (D-22). An error → E-G3, with `where=f"origin/{default_read['branch']}"`.
   - **G6.** Return `{"flag": head["flag"] or default["flag"], "error": None}`.

   The objects are local. AM-2 already verified that the local `origin/<D>` equals the remote SHA, so G5 makes no network call. `head_sha` is the range head that the caller already diffed.
4. **Messages.** They are S3-prefixed, because they replace S3's message (§5.2):
   - **E-G1:** `S3: human gate not verified: the default-branch read failed (see S4); failing closed`
   - **E-G2:** `S3: contract/step-manifest.yaml in the working tree does not match head {head_sha[:12]} ({detail}); commit or restore it, then re-run`, where `{detail}` is one of `modified`, `deleted`, `added but not committed`, `not a regular file`, or `unreadable: <strerror>`.
   - **E-G3:** `S3: could not read contract/step-manifest.yaml at {where} {sha[:12]} ({why}); failing closed, re-run`, where `{why}` is one of `timeout`, `exit N: <stderr line>`, `not a regular file`, or `not a full SHA`.
   - **E-G4:** `S3: head {head_sha!r} is not a full SHA; cannot pin the step manifest`
5. **Fail-closed conditions, enumerated.** Each of these makes the step count as behind the gate: a default-branch read error of any kind (E-F1 to E-F4); a non-full default or head SHA; a working-tree manifest that is missing, added, modified, non-regular or unreadable relative to head; a non-regular-file entry, a timeout or a git error at either SHA; and an undecodable or non-canonical manifest at either SHA (flag True, no error, so the generic S3 message). Absent at both SHAs, with the working tree also absent → False, which is unchanged from today for this repo, where no manifest exists.

**[AM-4 SR] Second-review hardening (2026-11-23, technical-design, #2392; from `.claudetmp/second-review/step2392-20261123T204903.md`).** The cross-vendor second review raised four findings against the AM-4 build at `59cc2f7d0`. Technical-design checked each one against the code and reproduced all four. **Rule for every SR item: the scanner may be stricter than a YAML parser, never looser.** The reference parsers are a last-key-wins loader such as PyYAML `safe_load` and a strict loader that rejects duplicate keys. If either one could see the step as gated, the scanner must return True. SR-1 to SR-3 live in `_manifest_scan`, so they apply to `manifest_human_gate_required` (path), the head read and the default read alike, and the T-G10 equivalence still holds. Each of them returns `(True, ids)` at once for the **whole scan**, not just for one item: once it is unclear which item is which step, no per-step answer is safe. They raise no error string, so the generic S3 message is used. SR-4 lives in `effective_manifest_human_gate` and has a named error. Change class `additive` (pure tightening). RISK: HIGH (D-7 input). CONFIDENCE: HIGH. #2410's deferred items (`GIT_*` env scrub, `splitlines`) stay out of scope. No SR rule depends on them (see SR-4).

- **[AM-4 SR-1] Duplicate key in one item → True** (agy high; reproduced). Today `items[-1].setdefault(key, …)` keeps the **first** `id:`, while YAML keeps the last or rejects the item. The repro is `- id: s1` / `id: s9` / `human_gate_required: false`, followed by a gated item that YAML reads as `s1`. It scans as `(False, …)`, but a parser sees `s1` as gated. The rule: in one item, a second key at `key_indent` whose normalised key (after `_yaml_scalar`) is `id` or `human_gate_required` → True. This holds for any item, not only the target item. The code must check whether the key is already present before it stores the key; `setdefault` must not be what resolves a duplicate. The `raw_hgr` count stays as it is, as a second net. Two **separate** items with the same id keep today's any-true rule, which is already at least as strict as first-wins or last-wins.
- **[AM-4 SR-2] A second or non-canonical top-level `steps` key → True** (agy high; reproduced). After an indent-0 line ends the block, a later `steps:` line re-enters it, and the `item_indent` from the first block is reused. The repro: block 1 lists `s1: false` and then `other`; a later `steps:` block lists `s1: true` at item indent 4. The scan returns False, while last-wins returns True. The same happens when the second block's items are at indent 0. The rule: take the key of every indent-0 line. That is the text before the first `:` that is followed by whitespace or end of line, after removing a leading `? `, normalised with `_yaml_scalar` and stripped of trailing spaces. The scan returns True if (a) more than one indent-0 key normalises to `steps`; (b) an indent-0 key normalises to `steps` but the line does not match the canonical `steps:(\s|$)` form, for example `"steps":`, `'steps':`, `steps :` or `? steps`, because the scanner does not enter those blocks and YAML does; or (c) a document marker line (`---` or `...`, at indent 0) appears after the first non-comment content line. A single leading `---` stays allowed.

  [SR round 2, AR-SR-2] **Key definition, independent of the colon.** An indent-0 line counts as a `steps` key if *either* candidate normalises to `steps`: the text before the **first `:` of any kind**, or the text before the first `:` that is followed by whitespace or end of line. In both cases a leading `? ` is removed first, then `_yaml_scalar`, then trailing spaces are stripped. This catches `"steps":[…]` and `steps:[…]` with no space after the colon. (a) and (b) above apply to that key. **Document marker:** any line matching `^(---|\.\.\.)(\s|$)`. The one allowed exception is a `---` line that comes before every non-comment content line **and** whose rest of line, after `---`, is empty or only a comment (`---` followed by whitespace and then `#…`). Every other marker line → True. That includes a leading `--- !tag`, a leading `--- steps: …`, a leading `...`, and any marker after content.
- **[AM-4 SR-3] Quoted, escaped, tagged or explicit keys, and non-canonical ids → True** (codex high, CWE-863; reproduced). `"human_gate_\x72equired": true` is the gate key to a YAML parser. But the raw `human_gate_required` substring count does not see it, and neither does the `_yaml_scalar` key match. So a gated item scans as False, and that fails open on the default-branch floor. The rule applies to every line in the file. Take the line's **key token**: the body after an optional leading `- `, up to the first `:` that is followed by whitespace or end of line. The scan returns True if:
  - (a) the key token starts with `"` and contains `\`, so it contains an escape;
  - (b) the key token starts with `'` and its inner text contains `'`, a `''` escape; this is defensive, because such a key cannot equal a reserved name;
  - (c) the key token starts with `!`, so it is a tagged key such as `!!str id`;
  - (d) the line's body (after an optional `- `) starts with `?` followed by whitespace or end of line, an explicit key;
  - (e) **on every read and whatever the result**, not only on the `None` path, any parsed item `id` value fails `_id_is_canonical`. This extends AR-AM4-2 (b) and SEC-R1. The repro is `- id: s1` / `human_gate_required: false` plus `- id: "s\x31"` / `human_gate_required: true`. That scans as `(False, ['s1', 's\\x31'])`, because the target is found, so the canonical check never ran; YAML sees a gated `s1`. It also catches a value on the next line (`id:` then `s1`, parsed as `""`) and a tagged value;
  - (f) an item inside the `steps:` block has no parsed `id`.

  [SR round 2, AR-SR-2] **(a) and (b) are defined by the quoted span at the start of the body, not by the key token.** These definitions replace (a) and (b) above. The *body* is the line with its indent removed, then an optional leading `-` and the whitespace after it. None of (a) to (d) depends on where any `:` is, so JSON-style adjacent colons (`"i\x64":s1`, `"human_gate_\x72equired":true`) are covered.
  - (a) The body starts with `"`. Scan forward to the first `"` that is not preceded by an unescaped `\`; that `"` closes the span. → True if the span contains a `\`, **or** no closing `"` occurs on the line.
  - (b) The body starts with `'`. Scan forward. A `''` pair is an escape. The first lone `'` closes the span. → True if the span contains a `''` pair, **or** no closing `'` occurs on the line.
  - (c) and (d) are unchanged: they test only how the body starts (`!`; `?` followed by whitespace or end of line).
  - A body that starts with a quoted span with no escapes and that closes on the line is unchanged, and is handled as today. `'human_gate_required': false` still gives False (T-G10).

  *Rejected alternative:* "any quoted key → True" is simpler, but it breaks `test_manifest_quoted_human_gate_key_is_read` (`'human_gate_required': false` → False). T-G10 requires that test to pass unchanged. A quoted key with no escape is decoded identically by the scanner and by YAML, so allowing it is not a loosening.
- **[AM-4 SR-4] G4 reads the working tree at the git toplevel, not at `repo_root`** (agy medium; real). G3 and G5 address the manifest from the toplevel (`ls-tree --full-tree`, `git show <sha>:<path>`). G4 used `Path(repo_root) / _STEP_MANIFEST_PATH`, and the CLI passes `"."`, so G4 is relative to the current directory. From a subdirectory, G4 compares the head blob with the wrong file. It can pass without checking anything (an untracked copy equal to head in `sub/contract/`, while the real working-tree manifest is modified), or it can fail spuriously. The flag itself still comes from the pinned blobs, so the gate value is not lowered directly. But G4's guarantee, that the working tree equals head, is void. This supersedes the "(cwd-relative)" wording in the §5.2 CLI paragraph and the "relative to `repo_root`" wording in §5.4, **for the working-tree read only**. The rule: G4 first runs `_git(["rev-parse", "--show-toplevel"], repo_root)`.
  - `None` → E-G5 `timeout`.
  - A non-zero exit → E-G5 `exit N: <_stderr_line>`. This covers a path outside any repo and a bare repo.
  - Otherwise decode stdout as strict UTF-8 and remove exactly one trailing `"\n"`, with `removesuffix`, not `splitlines` and not `strip`. Failure to decode, an empty result, a relative path or a path that is not an existing directory → E-G5 `not an absolute directory`.
  - Then `work = Path(toplevel) / _STEP_MANIFEST_PATH`, and the rest of G4 is unchanged.
  - **E-G5:** `S3: could not resolve the git toplevel from {str(repo_root)!r} ({why}); failing closed, re-run`, with `flag=True`.

  The order is G1, G2, G3, then G4 (rev-parse first), G5, G6. `GIT_DIR` and `GIT_WORK_TREE`, if set, affect `rev-parse`, `ls-tree` and `show` in the same way, so the three reads stay consistent without the #2410 env scrub.
- **[AM-4 SR-5] [SR round 2, AR-SR-1] Flag value spelling: only unquoted canonical false is False** (architect-found; CWE-863, same class as SR-3). Today `_yaml_scalar` strips the quotes and the comparison is `flag.lower() in ("false", "no", "0")`. So `"false"`, `'no'` and `fAlSe` scan as False. But `yaml.safe_load` returns the strings `'false'` and `'fAlSe'`, which are truthy, and under a YAML 1.2 core loader `no` is a truthy string too. The rule replaces the false-spelling check in `_manifest_scan`. For a found target item, let `v` be the value with its inline comment removed and surrounding whitespace stripped, **before** quotes are stripped:
  - The key is absent → no contribution (unchanged; the item gives False).
  - `v` does not start with `"` or `'`, **and** `v` is exactly one of `false`, `False`, `FALSE` or `0` → False.
  - Anything else → True. That includes any quoted value; mixed case (`fAlSe`); `no`, `No`, `NO`, `off`, `n`; `null`, `~`; an empty value (`human_gate_required:` with nothing after it); a tagged value (`!!bool false`); `0x0`, `00` and `0.0`; and garbage.

  These are the only spellings that YAML 1.1 and YAML 1.2 core both read as false (or as the falsy int 0). `contract/step-manifest.template.yaml` uses only `true`, and no existing fixture uses `no`, `0`, `off` or a quoted flag value (architect grep), so T-G10 holds.
- **[AM-4 SR-6] [SR round 2, AR-SR-4] Docstrings.** These are requirements on the code, checked at code review:
  - The `manifest_human_gate_required` and `_manifest_scan` docstrings must list every True condition: the existing ones; SR-1 (a duplicate `id`/`human_gate_required` in one item); SR-2 with AR-SR-2 (a second or non-canonical top-level `steps` key, and document markers); SR-3 with AR-SR-2 (escaped or unclosed quoted spans, tagged and explicit keys, non-canonical or missing ids); and SR-5 (any value other than an unquoted `false`/`False`/`FALSE`/`0`). The current phrase "true/false/yes/no/1/0" must be removed, because it is wrong after SR-5.
  - Both docstrings must state the **accepted false positives**. The scanner does not track block scalars, so a block-scalar text line that looks like a `? ` key, a `!` key, an escaped or unclosed quoted key, a document marker or a second `steps` key gates the whole manifest. This is by design, and the remedy is to write the manifest in canonical form.
  - The `effective_manifest_human_gate` docstring changes "E-G1..E-G4" to "E-G1..E-G5".

*Startup gap and affected sign-offs (SR).* Yes, these should have been settled in AM-4's first design: SR-1 to SR-3 belong to the same "scanner vs parser divergence" class as AR-AM4-2. Annotate #2214's `startup-artifact-gap`. The sign-offs at `59cc2f7d0` for code-review, security and test-unit are **orphaned** for `_manifest_scan` and `effective_manifest_human_gate`, and must re-review the SR delta. Security must specifically confirm SR-3's key-token definition. Reliability must confirm E-G5. The second review must re-run on the SR delta, and FINAL must run full-range. All other AM-1 to AM-4 sign-offs stand. **Architect review of this SR block is required before the coder implements it** (SR round 1 of 5). Human ruling needed: none, because every SR rule only tightens.

*[SR round 2] Folding of AR-SR-1 to AR-SR-4.* AR-SR-1 → SR-5 and T-G20. AR-SR-2 → the round-2 paragraphs under SR-2 and SR-3. AR-SR-3 → T-G19 (round 2). AR-SR-4 → SR-6. All four only tighten. SR-5 and AR-SR-2 fall inside the already-orphaned `_manifest_scan` scope, so the reviewer set is unchanged. Security's SR-3 confirmation must cover the AR-SR-2 quote-span definitions **and SR-5**. Noted, as the architect bound us: if a later round finds another case where the scanner reads looser than a parser, the fix is the allowlist of canonical line forms, not SR-7. **Status: awaiting architect confirmation of the folded text (SR round 2 of 5). The coder must not implement until it is confirmed.**

**[ARCH-AM4-SR] Architect ruling (2026-11-23, SR round 1 of 5): APPROVED with required changes AR-SR-1 to AR-SR-4.** SR-1 to SR-4 are each sound in what they cover. All four are strictly fail-closed. I re-ran the SR-1 and SR-3 repros against `59cc2f7d0`, and both scan as `(False, ['s1', …])`, which confirms the findings. None of the rules can turn an existing True into False. No existing `test_manifest_*` fixture has a duplicate key, a second `steps`, an escaped, tagged or explicit key, a non-canonical id or an id-less item where False is expected. `contract/step-manifest.template.yaml` passes every SR rule: its ids are integers, the only flag value is `true`, and there are no `---` lines and no quoted keys. So consumer manifests in template form do not change. SR-1's "check before store" is the correct fix for the first-wins `setdefault`. Keeping the any-true rule across separate items is correct. SR-4 is correct. `rev-parse --show-toplevel` fails with 128 in a bare repo and outside a repo, so G4 can no longer pass without checking anything. Using `removesuffix` and not `strip` is correct, because a toplevel path can end in whitespace. E-G5 fits the scheme: it has the S3 prefix, `flag=True`, the same `why` wording as `read_manifest_gate_at` (`timeout` / `exit N: …`) and the same "failing closed, re-run" ending as E-G3. It is correctly a separate error from E-G2, because a toplevel that cannot be resolved is not a mismatch.

The block's own rule is "if either reference parser could see the step as gated, return True". That rule is not yet fully met. AR-SR-1 is a fail-open of the same CWE-863 class as SR-3, and the coder must not implement SR without it.

- **AR-SR-1 (new SR-5: spelling of the flag value).** At `59cc2f7d0`, `human_gate_required: "false"`, `'no'` and `fAlSe` all scan as `(False, ['s1'])`. `_yaml_scalar` strips the quotes and the comparison is `lower()`. But `yaml.safe_load` returns the strings `'false'` and `'fAlSe'`, and both are truthy. Under a YAML 1.2 core loader (the second reference parser), `no` is also a truthy string. The fix: a found target's value counts as False **only if** it is unquoted (the comment-stripped value does not start with `"` or `'`) and is exactly one of `false`, `False`, `FALSE` or `0`. Every other value → True: quoted values, mixed case, `no`/`No`/`NO`, `off`, `null`, `~`, an empty value, a tagged value. I grepped `tests/`, `contract/`, `scripts/` and `templates/`. No fixture or template uses `no`, `0`, `off` or a quoted flag value, so T-G10 holds. Add T-G20 for these spellings, and add each one to the T-G19 oracle set.
- **AR-SR-2 (definitions that do not depend on where the colon is).** SR-3 (a) and (b) are defined on a key token that ends at the first `:` followed by whitespace. That token is undefined for `"i\x64":s1` and `"human_gate_\x72equired":true`. Those are JSON-style adjacent colons. PyYAML rejects them, but a YAML 1.2 loader accepts them, and the existing `partition(":")` reads them as keys. The fix: (a) fires when the body (after `-` and any whitespace) starts with `"` and the double-quoted span up to its first unescaped `"` contains `\`, **or** that quote does not close on the line. (b) is the same for `'`, with `''` or an unclosed quote. (c) and (d) test only how the body starts. None of the four depends on a colon. SR-2's indent-0 key fires if the text before the **first `:` of any kind**, or the text before the first `:` followed by whitespace, normalises to `steps`. That catches a second `"steps":[…]`. A document marker is a line matching `^(---|\.\.\.)(\s|$)`. The single leading `---` is allowed only when the rest of its line is empty or a comment.
- **AR-SR-3 (the oracle must not skip).** `PyYAML>=6.0` is declared in `scripts/oversight/requirements.txt`, and other tests already `import yaml` unconditionally. T-G19 must import it the same way: no `importorskip`, no skip marker. As written, the oracle could silently do nothing in the PR-required suite. The oracle compares `str(item.get("id")) == step`, not `== "s1"`, so that a numeric fixture counts too: step `7` against `id: 007` and against `id: 0x7`, both `true`, next to a canonical `7: false`. Each must scan True. Fixtures that PyYAML rejects stay covered by the explicit asserts in T-G14 to T-G17 and T-G20.
- **AR-SR-4 (docstrings).** Rewrite the docstrings of `manifest_human_gate_required` and `_manifest_scan` to list the SR-1 to SR-3 and AR-SR-1 conditions. The current "true/false/yes/no/1/0" is wrong after AR-SR-1. They must also state the accepted false positives: a block-scalar text line that looks like a `? `, `!`, escaped-quote or second-`steps` key gates the whole manifest, by design, and the fix for that is canonical form. Change the `effective_manifest_human_gate` docstring from "E-G1..E-G4" to "E-G1..E-G5".

*Proportionality (binding).* Keep the line scanner, and do not swap in PyYAML in this step. `suspension_manager` is stdlib-only, so the gate runs on the base interpreter. `safe_load` is last-key-wins, so it would still need a custom loader that rejects duplicates. A parser also does not settle YAML 1.1 versus 1.2 value semantics; AR-SR-1 settles that by accepting only the spellings both versions agree on. #2410's env scrub and `splitlines` stay deferred: the characters that only `splitlines` treats as line breaks (`\x0b`, `\x0c`, `\x1c`–`\x1e`) are non-printable, and PyYAML's reader rejects them, so they open no gap where the scanner is looser. **Condition for converging:** if any later round finds another case where the scanner reads looser than a parser, the fix is not SR-n+1. It is to replace the denylist with an allowlist of canonical line forms inside `steps:`, where any line that matches no form → True. I will require that change at that point.

*Affected sign-offs.* I agree with technical-design's analysis above. AR-SR-1 and AR-SR-2 fall inside the same orphaned scope (`_manifest_scan`), so the reviewer set does not grow. Security's SR-3 confirmation must cover the AR-SR-2 quote-span definitions. Product boundary: no checkpoint is needed. Every change only raises True on the S3 path of the dep-mapper LOW suspension, in the D-7 direction, and the template is unaffected. **Next:** technical-design folds AR-SR-1 to AR-SR-4 into this block and the §10(i) tests. Then the architect confirms the folded text in SR round 2, and only after that does the coder implement.

**[ARCH-AM4-SR round 2] Architect ruling (2026-11-23, SR round 2 of 5): APPROVED.**

- **Each AR is met.** AR-SR-1 → SR-5 and T-G20. AR-SR-2 → the round-2 paragraphs under SR-2 and SR-3, plus T-G15b and T-G16b. AR-SR-3 → T-G19 round 2, with an unconditional `import yaml` and `str(id) == str(step)`. AR-SR-4 → SR-6.
- **I checked the fold for new looseness and found none.** Each point below either matches YAML or comes out stricter:
  - **SR-5.** `v` is taken before the quotes are stripped, so a quoted falsy value gives True. The comment regex requires whitespace before `#`, so `false#x` gives True. Only `false`, `False`, `FALSE` and `0` give False.
  - **SR-3 (a)/(b) quote spans.** These close at the first unescaped quote. Any escape in the span, and any span left unclosed on the line, gives True. A clean quoted key keeps today's handling (`_yaml_scalar` reads it the same way YAML does), so the T-G10 controls are unchanged.
  - **A `#` inside a quoted key.** `_yaml_scalar` can read such a key as a reserved name. That can only add a match, and SR-1 or `raw_hgr` turns any resulting duplicate into True.
  - **SR-2.** With both colon candidates and the `steps:(\s|$)` canonical test, `steps:[…]` and `"steps":` give True through (a) or (b). The marker rule allows only a bare or comment-only leading `---`. A leading `--- !tag`, a leading `--- steps:` and a leading `...` all give True.
- **The SR round-1 sign-off paragraph still has two stale phrases.** "SR round 1 of 5" and "SR-3's key-token definition" are superseded by technical-design's round-2 fold note, which governs. No edit is required.
- **Non-blocking note for the coder.** In the T-G19 oracle, skip any `steps` item that is not a dict (`isinstance(item, dict)`) before calling `.get`. Otherwise a fixture such as `- s1` crashes the test instead of being checked. The scanner already returns True for such an item under SR-3(f).
- **The coder may implement** SR-1 to SR-6 as folded. The sign-off and re-review obligations in the paragraphs above still apply.

**[AM-4 SR-AL] Allowlist of canonical line forms inside `steps:` (SR round 3, 2026-11-23, technical-design, #2392).**

*Trigger.* The security round-SR review of `784c270f0` (register `## security (round SR)`; probes in `.claudetmp/probe2392sr.py` and `fuzz2392sr.py`) found two more cases where the scanner reads looser than PyYAML:
- **(1) Unicode whitespace.** `human_gate_required: false` padded with U+00A0, U+3000, U+2003, U+202F, U+1680 or U+200A scans False. So do a leading NBSP and an NBSP before `#`. The cause is that `str.strip()` and `\s` are Unicode-aware. YAML whitespace is space and tab only, so PyYAML reads a truthy string.
- **(2) Plain-scalar continuation.** `human_gate_required: false` followed by a deeper-indented `true` scans False, but YAML reads `'false true'`. The id case is the same: `id: 5` followed by a deeper `x` gives the id `'5 x'`.

That meets the binding convergence condition in [ARCH-AM4-SR]. So there is **no SR-7**. Inside the `steps:` block, the scanner now accepts a line only if it matches one of the forms below, and **any other line makes the whole scan return `(True, ids)`**. Change class `additive` (pure tightening; see "Consequence" below). RISK: HIGH (D-7 input). CONFIDENCE: HIGH that the grammar is never looser than PyYAML. MEDIUM on the consumer impact of refusing nested content, which is disclosed below.

**AL-0. Scope, matching and whitespace.**
- The *steps block* is every line after the canonical `steps:` line, up to the first indent-0 line that does not start with `-`. Lines outside the block keep today's rules: the global anchor and merge-key check, SR-2, and the existing top-level handling.
- Every form below is matched with `re.fullmatch` on the **raw line**, compiled with `re.ASCII`. No `strip`, `lstrip`, `split()`, `\s`, `\w` or `\d` may be used on a steps-block line. Indent is the count of leading U+0020 characters only.
- `S` = one or more U+0020 characters. `W` = `[ \t]` (U+0020 or U+0009). Tab is allowed only in the comment separator and in blank or comment lines, never in indentation and never after `-`.
- `END` = `(?:[ \t]+(?:#.*)?)?`. That is optional trailing ASCII whitespace, then an optional comment, which must be preceded by at least one space or tab. Comment text (`.*`) may contain any character, including non-ASCII, because YAML discards it.
- The canonical `steps:` line itself must fullmatch `steps:END`. Any other form is SR-2's business, which still applies.

**AL-1. Line forms (the complete allowlist).** Inside the steps block, a line is canonical only if it is one of these:
- **L-blank:** `[ \t]*`. A line holding only Unicode spaces, such as NBSP, is **not** blank.
- **L-comment:** `[ \t]*#.*`.
- **L-item:** `(?P<ind> *)- +(?P<body>KV)`. The first L-item sets `item_indent = len(ind)`, and every later L-item must have exactly that indent. Its `key_indent` = `len(ind)` + 1 + the number of spaces after `-`. A bare `-` with nothing after it, a tab after `-`, and `- ` followed by anything that is not `KV` are all rejected.
- **L-key:** ` {key_indent}KV`. That is exactly `key_indent` spaces, where `key_indent` belongs to the current item, followed by `KV`. An L-key before the first L-item is rejected.
- `KV` = `KEY: +VALUE(key)END`. At least one space after the colon. **The value may not be empty**, for any key: an empty value would start nested content (AL-3). `key: value` with no space after the colon is rejected.
- `KEY` = `[A-Za-z_][A-Za-z0-9_-]*`, either plain or wrapped in `"…"` or `'…'` with the same inner grammar. The normalised key is the inner text. So a quoted key cannot contain an escape, `''`, a space, a `#` or non-ASCII. Tagged keys (`!`), explicit keys (`?`), anchors, aliases and flow collections cannot match.

**AL-2. Value grammar (ASCII fullmatch, per key).**
- **`VALUE(id)`** is one of `ID`, `'ID'` or `"ID"`. `ID` must pass `_id_is_canonical`, which is unchanged (`[A-Za-z0-9._/-]+`, and numeric-looking ids must be canonical integers). In addition, a **plain** `ID` must not fullmatch, case-insensitively, `y|yes|n|no|true|false|on|off|null`. YAML 1.1 reads those words as a bool or null, so `str(id)` would be `True` or `None`, not the text. The quoted forms are strings, so they may use those words. The parsed id is the inner text.
- **`VALUE(human_gate_required)`** must be a plain value. `false`, `False`, `FALSE` and `0` give False. `true`, `True`, `TRUE` and `1` give True. **Anything else is not canonical**, so the line fails and the whole scan returns True. That includes quoted values, other spellings, tags and Unicode padding.
- **`VALUE(other key)`** is one of the following:
  - `PLAIN` = `[A-Za-z0-9_.][A-Za-z0-9_./-]*(?: [A-Za-z0-9_./-]+)*`. Words are joined by single spaces. There is no `:`, `#`, quote, bracket, brace, `,`, `&`, `*`, `!`, `|`, `>`, `%`, `@`, backtick or leading `-`.
  - `DQ` = `"[^"\\\x00-\x1f\x7f]*"`, a double-quoted span closed on the same line, with no backslash and no control characters.
  - `SQ` = `'(?:[^'\x00-\x1f\x7f]|'')*'`, a single-quoted span closed on the same line. `''` is fine inside a value.
  - `FLOW` = `\[ *(?:TOK(?: *, *TOK)*)? *\]`, with `TOK` = `[A-Za-z0-9_][A-Za-z0-9_./-]*`. This is a flow sequence of plain tokens, closed on the line.

  A block-scalar indicator (`|`, `>`), a flow mapping, an anchor, an alias, a tag and an unclosed span cannot match. So no other-key value can start a multi-line construct. Any continuation line that YAML would attach to the value is deeper than `key_indent`, and AL-3 rejects it.

**AL-3. Deeper and shallower lines.** No nested content is allowed. Any non-blank, non-comment line in the steps block is rejected unless it is an L-item at exactly `item_indent` or an L-key at exactly the current `key_indent`. That covers:
- continuation lines of a plain scalar (finding 2, for the flag, the id or any other key);
- nested block sequences or mappings (`required_signoffs:` followed by `      - code-review`);
- items at a different indent;
- lines between `item_indent` and `key_indent`;
- tab-indented lines.

*Check against the canonical manifests.* `contract/step-manifest.template.yaml` uses only L-blank, L-comment (including indented, commented-out example items), L-item and L-key. Its ids are integer `ID` values; `risk_tier` is `PLAIN`; `name` is a `DQ` that contains non-ASCII (`—`); `required_signoffs` is a `FLOW`; `system_test_applicable` is `PLAIN`; and `human_gate_required: true` is canonical. So the template scans step 3 → True and steps 1 and 2 → False, which is unchanged. This repo has **no** `contract/step-manifest.yaml` (the real configuration is T-G7, absent everywhere). Every existing fixture that expects False uses only these forms: `id: 's1'`, `false # ok`, `name: y`, and `required_signoffs: [code-review, security]`. The one existing nested-list fixture (`test_manifest_nested_list_does_not_start_a_new_item`) already expects True.

*Consequence (disclosed in the PR's human summary).* A consumer manifest that writes `required_signoffs` (or any key) as a nested block list, a block scalar or a multi-line value now has **every** step counted as human-gated for the dep-mapper LOW suspension only. That is fail-closed, and the remedy is to rewrite that key in flow or single-line form. Nothing else reads this scan (§5.2.2 item 1).

**AL-4. Non-ASCII in the steps block.** It is allowed in exactly two places:
- inside comment text, meaning after the `#` of an L-comment or of `END`;
- inside a closed `DQ` or `SQ` value of an **other** key.

Anywhere else it means the line fails, so the scan returns True. That covers indentation, after `-`, keys, `id` values, flag values, `PLAIN` and `FLOW` values, the separator before `#`, and trailing whitespace. This fixes finding 1 in every position. U+0085, U+2028 and U+2029 inside a quoted span are split by `splitlines` (and by PyYAML) into two lines. The first of those is then an unclosed span, so the line fails. This holds without the #2410 `splitlines` change, which stays out of scope.

**AL-5. What the allowlist subsumes, and what stays.**

| Rule | Inside the steps block | Status |
|---|---|---|
| SR-3 (a)–(d) quoted/escaped/tagged/explicit keys | `KEY` grammar | **Subsumed** inside the block. `_bad_quoted_span` stays only if the coder still uses it for top-level lines (SR-2); otherwise delete it, along with its tests. |
| SR-3 (e) non-canonical id | `VALUE(id)` | **Subsumed** (and tightened by the YAML 1.1 reserved words). `_id_is_canonical` stays as a helper. |
| SR-5 flag spelling | `VALUE(human_gate_required)` | **Subsumed**. A non-canonical flag now fails the whole scan, not just the item. |
| Brace/flow checks, anchors and merge keys *inside* the block | `KV` and `VALUE` grammar | **Subsumed** inside the block. The global anchor and merge-key check **stays** for lines outside it. |
| SR-1 duplicate key in one item | cross-line | **Stays**, generalised: a duplicate of **any** normalised key in one item → True. |
| SR-2 second or non-canonical top-level `steps`; document markers | outside the block | **Stays** unchanged. `_is_steps_key_line` stays. |
| SR-3 (f) item without `id` | cross-line | **Stays**. |
| `raw_hgr` count | — | **Stays** as a redundant net. It is stricter; for example `name: human_gate_required` still gates. |
| AR-AM4-1 (`None` only if a `steps:` block was entered) and AR-AM4-2 (default-read token check) | — | **Stay** unchanged. |
| SR-4 toplevel / E-G5 | — | **Stays**, with the AL-6 wording fix. |

*Proportionality.* The scanner stays line-based and stdlib-only. PyYAML is still not used at runtime ([ARCH-AM4-SR]). The coder implements the grammar as one helper, **`_classify_steps_line(line: str) -> tuple[str, int, str | None, str | None] | None`**. It returns `(kind, indent, key, value)`, where `kind` is one of `blank`, `comment`, `item` or `key`, and `value` is the normalised inner text. `None` means the line is not canonical. The value grammar is applied per key inside the helper. `_manifest_scan` applies the AL-3 indent rules, SR-1 and SR-3(f) on top of it. The docstrings (SR-6) must describe the allowlist, not the retired denylist entries.

**AL-6. Reliability nit (register `## reliability (round SR)`): accepted for E-G5 only.**
- `_git` returns `None` on a timeout **and** on an `OSError` (for example, git is not installed), so E-G5's `why` becomes `timeout or git could not start`.
- A non-zero exit with empty stderr gives `exit N`, not `exit N: `.
- E-G3 and the suspension-file messages keep `timeout` and `exit N: …`, because T-F12 pins them byte for byte. Aligning them is a follow-up, not this step.

*Startup gap and affected sign-offs (SR round 3).* Same `startup-artifact-gap` annotation on #2214. The sign-offs for `784c270f0` that cover `_manifest_scan` and the new helper are orphaned: code-review, security, test-unit and reliability (for E-G5). They must re-review the SR-AL build. Security must re-run `probe2392sr.py` and `fuzz2392sr.py` against it and record zero looser-than-PyYAML cases. The second review re-runs on the delta, and FINAL runs full-range. Human ruling needed: none for correctness, because this only tightens. The nested-content consequence is disclosed, not ruled. **Status: awaiting architect review of SR-AL (SR round 3 of 5). The coder must not implement until it is approved.**

**[SR round 4] Folding of AR-AL-1 to AR-AL-3 into SR-AL.** Where these paragraphs conflict with AL-0, AL-5 or SR-6 above, these paragraphs govern.
- **[SR round 4, AR-AL-1] How the block ends. This replaces AL-0's block-end definition.** `_manifest_scan` classifies each line of the steps block in this order:
  1. **L-blank and L-comment come first, at any indent, including column 0.** Such a line is skipped and **never ends the block**.
  2. **The block ends only at a line whose first character is an ASCII printable character other than U+0020, `-` and `#`** (that is, in `[!-~]` minus `-` and `#`). That line is then handled by the outside-block rules (SR-2, SR-3 (a)–(d), and anchors and merge keys).
  3. **A line whose first character is a tab, a non-ASCII character or any other non-printable character, and which is not L-blank or L-comment, does not end the block.** It is a non-canonical line inside the block, so the whole scan returns `(True, ids)`. A line starting with NBSP is therefore never treated as top-level.
  4. Every other line is checked against L-item and L-key, and against AL-3.

  The repro, a column-0 `# c` between a `false` item and a `true` item with the same id, now reaches the second item. The scan returns True through the existing any-true rule for separate items with the same id.
- **[SR round 4, AR-AL-2] SR-3 (a)–(d) stay mandatory outside the block. This replaces AL-5's first row and its "otherwise delete it" sentence.** `_bad_quoted_span`, with the AR-SR-2 quote-span definitions, together with the `!`-key and `?`-key checks of SR-3 (c) and (d), **must** run on every line outside the steps block. That covers top-level lines before the block, the line that ends it, and every line after it. Any hit → `(True, ids)`. They are subsumed only **inside** the block, by the `KEY` grammar. The reason: SR-2 normalises keys with `_yaml_scalar`, so `"st\x65ps":` and `!!str steps:` do not normalise to `steps`. Without these checks, a second block that YAML reads last-wins would be ignored. `_bad_quoted_span` is not deleted, and its T-G21 direct tests stay.
- **[SR round 4, AR-AL-3] Making the remedy discoverable.**
  - The coder adds **one comment line** to `contract/step-manifest.template.yaml`, directly above the `steps:` line. That places it outside the block, where L-comment applies and the scan is unaffected. It must say that step entries use single-line values only, with lists in flow form (`[a, b]`), because nested or multi-line values make every step count as human-gated for the dep-mapper LOW suspension.
  - This is a `contract/**` edit, so it is a protected surface. It falls inside this HIGH, human-gated step and adds the template to the §9 build list as a coder file.
  - The SR-6 docstrings of `manifest_human_gate_required` and `_manifest_scan` must state the same rule and the same consequence. They must also describe the AR-AL-1 block-end rule and the AR-AL-2 outside-block checks.
  - The AL-3 "Consequence" disclosure in the PR's human summary stays, and must name the new template comment as the remedy pointer.

*Sign-offs (SR round 4).* No new reviewer. AR-AL-1 and AR-AL-2 fall inside the orphaned `_manifest_scan` scope. Security's re-run of `probe2392sr.py` and `fuzz2392sr.py` must include column-0 comments, column-0 blank lines, lines starting with a tab or NBSP between items, and escaped or tagged top-level `steps` keys. Code-review covers the template comment. **Status: awaiting architect confirmation of the fold (SR round 4 of 5). The coder must not implement until it is confirmed.**

**[ARCH-AM4-SR round 3] Architect ruling (2026-11-23, SR round 3 of 5): APPROVED with required changes AR-AL-1 to AR-AL-3.**

*What is sound.* The allowlist is the convergence fix I required, and its structure is right.
- **Inside the block, every line is checked.** Each line must fullmatch an ASCII-compiled form, and anything else → True.
- **ASCII is enforced at every position that matters.** Indentation counts U+0020 only. Non-ASCII is allowed only in comment text and inside closed `DQ`/`SQ` values of other keys, which YAML reads as string content or discards.
- **Both findings are closed.** An other-key value can no longer start a multi-line construct: there is no `|`, `>`, unclosed span, flow mapping, anchor or tag. AL-3 rejects every deeper line. Together these close finding 2 for every key, and AL-4 closes finding 1.
- **The id and flag grammars are correct.** `VALUE(id)` adds the YAML 1.1 reserved words. `VALUE(human_gate_required)` fails the whole scan, not just the item.
- **The kept checks are correct.** SR-1 (now any key), SR-2, SR-3(f), `raw_hgr`, AR-AM4-1 and AR-AM4-2 can only add True.
- **The template still scans correctly.** I fullmatched every line after `steps:` in `contract/step-manifest.template.yaml` against a prototype of the AL-1/AL-2 grammar. No line is rejected, so the template still scans 3 → True and 1, 2 → False.
- **AL-6 is accepted.** It is scoped to E-G5, and E-G3 stays byte-pinned by T-F12.

**Required changes.** AR-AL-1 and AR-AL-2 are fail-opens.
- **AR-AL-1 (how the block ends).** Read literally, AL-0 ends the block at "the first indent-0 line that does not start with `-`". So a column-0 comment ends it. PyYAML, run against this repo's venv, loads
  ```
  steps:
    - id: s1
      human_gate_required: false
  # c
    - id: s1
      human_gate_required: true
  ```
  as two `s1` items, and the second is gated. The scanner would stop at `# c`, ignore the second item and return False. The fix: classify L-blank and L-comment **before** testing for the end of the block. Those lines never end it. The block ends only at a line that is neither L-blank nor L-comment and whose first character is an ASCII printable other than U+0020, `-` or `#`. A line whose first character is a tab or non-ASCII, and that is not L-blank or L-comment, is a non-canonical line inside the block → True. It does not end the block. Add T-G21b covering three cases: the repro above → True; the same with a column-0 blank line → True; a line starting with NBSP or a tab between items → True.
- **AR-AL-2 (keep SR-3 (a)–(d) for every line outside the block).** AL-5 lets the coder delete `_bad_quoted_span` "if not used for top-level lines". It must not be deleted. SR-2 normalises a key with `_yaml_scalar`. So `"st\x65ps":`, `!!str steps:` and similar spellings of a second top-level `steps` key do not normalise to `steps`. Without SR-3 (a)–(d) on outside lines, YAML's last-wins second block would be ignored → False. The fix: SR-3 (a)–(d), with the AR-SR-2 quote-span definitions, stay **mandatory for every line outside the steps block**. Change the AL-5 row to "Subsumed inside the block; **stays** for every line outside it". Add T-G25b covering `"st\x65ps":` and `!!str steps:`, each as a second top-level block that lists `s1: true` after a canonical `s1: false` block → True.
- **AR-AL-3 (make the consumer remedy discoverable).** The consequence of AL-3 is acceptable as a fail-closed change:
  - `manifest_human_gate_required` and the SHA-pinned gate are on `main` only. They are absent from `v0.6.0` (git grep), so no released consumer regresses.
  - The canonical template is unaffected.
  - The only effect is more human gating on the dep-mapper LOW suspension path, which is the D-7 direction.
  - No cost, retention, topology or new-service consequence → no product-boundary checkpoint is needed.

  But the generic S3 message does not tell a consumer why every step is gated. The fix: add one comment line above `steps:` in `contract/step-manifest.template.yaml`, which is outside the block and so has no effect on the scan. It states that step entries must use single-line values, with lists in flow form (`[a, b]`), because nested or multi-line values gate every step for the dep-mapper suspension. Also state the same in the SR-6 docstrings.

*Next.* Technical-design folds AR-AL-1 to AR-AL-3. Then the architect confirms the fold in SR round 4. Only after that does the coder implement. The SR-AL sign-off analysis above stands. AR-AL-3 adds a `contract/` edit, which is a protected surface and is already inside this HIGH, human-gated step.

**[ARCH-AM4-SR round 4] Architect ruling (2026-11-23, SR round 4 of 5): APPROVED.** The fold satisfies AR-AL-1 to AR-AL-3, and I found no new looseness.
- **AR-AL-1.** Blank and comment lines are classified first and never end the block. That makes the column-0 `# c` repro reach the second item, and the any-true rule then returns True.
  - The end-of-block set is `[!-~]` minus `-` and `#`. Every character in that set either starts a real top-level key or reaches an outside-block check that returns True:
    - `"` and `'` with an escape, or left unclosed, hit SR-3 (a)/(b). `!` hits (c) and `?` hits (d).
    - `&` and `*` hit the global anchor check.
    - `%`, `[`, `{`, `|` and `>` at column 0 after a block mapping are YAML errors.
  - A line starting with a tab, NBSP, another non-ASCII character or a control character returns True and does not end the block. So no line YAML would keep inside `steps` can end the block early.
- **AR-AL-2.** `_bad_quoted_span` and the `!` and `?` checks are now mandatory on every line outside the block, including the line that ends it. That closes the `"st\x65ps":` and `!!str steps:` second-block path. T-G25b covers it, including the unclosed-quote and `? steps` variants.
- **AR-AL-3.** The template comment goes above `steps:`, outside the block, so the scan is unaffected. The T-G24 text assertion pins it. The docstrings and the PR's human summary name the remedy. No product-boundary checkpoint is needed, for the reasons in round 3.
- **Tests.** T-G21b's control (column-0 comment and blank between distinct `false` items → False) proves that the block continues past them and is not just failing closed. All the new fixtures feed the T-G19 oracle.

The coder may implement SR-1 to SR-6, SR-AL (AL-0 to AL-6) and the round-4 fold. Where they conflict, the round-4 paragraphs govern AL-0, AL-5 and SR-6. The sign-off and re-review obligations in the SR, SR-AL and round-4 sign-off paragraphs stand. Security's re-run of `probe2392sr.py` and `fuzz2392sr.py` must record zero cases where the scanner reads looser than PyYAML before security signs off. The SR loop closes at round 4 of 5.

**[ARCH-AM4-SR round 5] Architect arbitration (2026-11-23, security vs design on the `splitlines` residual at `21f829203`): ruling (A). Fold it in now as AR-AL-4 with test T-G26.**

*Why the round-1 deferral was wrong for three of the characters.* My [ARCH-AM4-SR] proportionality paragraph deferred `splitlines` to #2410. Its reason was that the characters only `splitlines` treats as line breaks are non-printable and rejected by PyYAML. That holds for VT, FF and U+001C–U+001E: both YAML 1.1 and YAML 1.2 reject them as non-printable, so no loader sees content there. It does not hold for U+0085, U+2028 and U+2029:
- PyYAML (YAML 1.1) treats them as line breaks, which agrees with `splitlines`.
- A YAML 1.2 loader treats them as ordinary content characters.

This block's own rule names a strict loader as a second reference parser. AR-SR-1 relied on YAML 1.2 core semantics when it ruled on `no`. So the rule is "never looser than *either* parser", and the 118 divergent inputs that security emulated are in scope. Security is right, and the deferral reasoning is superseded for these characters.

*Why (A) and not (B).*
- **The fix is one line and strictly fail-closed.** It cannot make an existing True become False.
- **The canonical template contains none of these characters.** Its only non-ASCII character is U+2014, so it is unaffected.
- **A consumer manifest that contains them is gated, by design.** Each character is either invisible or rejected by one of the parsers, so gating is the correct answer.
- **Deferring would knowingly ship a fail-open.** It would sit on the D-7 floor that this whole block exists to close.

**AR-AL-4.**
- `_manifest_scan` returns `(True, [])` before any line processing if the decoded text contains any of these characters: U+000B, U+000C, U+001C, U+001D, U+001E, U+0085, U+2028 or U+2029. It applies to the whole text, including comments and quoted spans. It runs on the path function and on both pinned reads.
- Use the **contains-check**, not "split on LF, CRLF and CR only". Re-splitting would create a new divergence in the other direction: PyYAML *does* break on U+0085, U+2028 and U+2029. Rejecting these characters is the only treatment that satisfies both parsers.
- `str.splitlines()` may stay for the remaining characters. Once these are excluded, it splits only on LF, CR and CRLF, which every YAML version treats as line breaks.
- AL-4's sentence about U+0085, U+2028 and U+2029 inside quoted spans is superseded, because such text now never reaches the line rules.
- The SR-6 docstrings list this condition.

**T-G26.**
- **True cases:** for each of the eight characters, three placements must return True: `human_gate_required: false<c>` on a target item, `<c>` inside a comment, and `<c>` inside a `DQ` value of another key. Check the path function and both pinned reads. Also run one end-to-end case: the default branch has `false<U+2028>` and head is canonical `false`, so the effective gate is True.
- **Control:** the template, which contains U+2014, still scans steps 1, 2 and 3 as False, False and True. A `DQ` value containing U+00A0 still scans False, because NBSP is not one of the listed characters and AL-4 allows it inside a closed span.
- **Oracle:** add all of these fixtures to T-G19.

*Startup gap and affected sign-offs.* Yes, this should have been settled in round 1, and the mistake was my rationale. Annotate #2214's `startup-artifact-gap`. The sign-offs at `21f829203` stand except for `_manifest_scan`:
- Security, code-review and test-unit re-review the AR-AL-4 delta only.
- Security confirms that the 118 emulated inputs now scan True.
- The second review re-runs on the delta, and FINAL runs full-range.

The coordinator updates #2410 to drop the `splitlines` item and records this ruling there. The `GIT_*` env scrub stays deferred.

*Loop cap.* This was round 5 of 5 of the SR loop. I am not opening a sixth design round. If any further reviewer finding shows the scanner reading looser than a parser, I will escalate it to the human on record, with this history, and will not rule on it inside the loop.

**[AM-4 AL-WD] Whole-document canonical-line allowlist (human ruling A on #2392, 2026-11-24; technical-design, 2026-11-25).**

*Status and standing.* This block **records and implements a human ruling**. It is not a sixth SR design round. The architect reviews it only for fidelity to the ruling and for any new looseness, and does not re-open the choice between options. Change class `additive` (pure tightening). RISK: HIGH (D-7 input; `contract/**`-adjacent behaviour). CONFIDENCE: HIGH that the grammar is never looser than PyYAML or a YAML 1.2 loader. That rests on the completeness argument in AL-WD-6, a prototype run, and a 200 000-document random-fragment fuzz against PyYAML with 0 looser cases. The fuzz is small evidence: only 21 of its documents were gated. CONFIDENCE is MEDIUM on how many consumers are affected (AL-WD-8).

*Trigger.* The FINAL second review (`.claudetmp/second-review/step2392-20261123T232742.md`, agy, request_changes) found two cases where the scanner reads looser than the parser. Technical-design reproduced both **verbatim** against `909dfb278` with the repo venv's PyYAML:
- **F1 (indented document).** Text:

  `'  foo: "x\nsteps:\n  - id: s1\n    human_gate_required: false\nx"\n  steps:\n    - id: s1\n      human_gate_required: true\n'`

  `yaml.safe_load` returns `{'foo': 'x steps: - id: s1 human_gate_required: false x', 'steps': [{'id': 's1', 'human_gate_required': True}]}`. `_manifest_scan(text, "s1")` returns `(False, ['s1'])`.
- **F2 (BOM).** Text:

  `'﻿steps:\n  - id: s1\n    human_gate_required: true\nfoo: "x\nsteps:\n  - id: s1\n    human_gate_required: false\nx"\n'`

  `yaml.safe_load` skips the leading BOM and returns `{'steps': [{'id': 's1', 'human_gate_required': True}], 'foo': 'x steps: - id: s1 human_gate_required: false x'}`. `_manifest_scan` returns `(False, ['s1'])`.

*Root cause.* The SR-AL allowlist covers only lines inside the `steps:` block. Outside the block, the scanner uses a denylist:
- it checks for an unclosed quote only when the line's body *starts* with a quote, so in `foo: "x` the open quote comes after the key and is missed;
- it never recognises an indented `steps:` key or a BOM-prefixed `steps:` key as the top-level key.

So a multi-line value outside the block can hide a decoy column-0 `steps:` block, while YAML reads the real block somewhere else.

*Human ruling (verbatim, #2392, 2026-11-24).* "extend the canonical-line allowlist to the whole document, and gate any indented first line or BOM. That closes both cases by construction rather than case by case, and it fails toward gated. Cost: one coder round plus a second review." Two low agy items, L1 and L2, are folded in below. The human did not object to them.

**AL-WD-0. Scope.** AL-WD covers every line that is **not** handled by the in-block rules: lines before the canonical `steps:` line, the `steps:` line itself, the line that ends the block (AR-AL-1 item 2), and every line after it. The in-block rules (AL-0 to AL-5 as amended by AR-AL-1, SR-1, SR-3(f), SR-5) are **unchanged**. AL-0's matching rules apply to outside lines without exception: `re.fullmatch` on the raw line, `re.ASCII`, and indent counted as leading U+0020 only. No `strip`, `split()`, `\s`, `\w` or `\d` may be used to accept an outside line. The existing nets may keep their current regexes, because they can only add True.

**AL-WD-1. Whole-text pre-scan (extends AR-AL-4).** AR-AL-4 already applies to the whole text: `_manifest_scan` checks `_LINE_BREAK_AMBIGUOUS.isdisjoint(text)` before any line is read (`suspension_manager.py:1111`). AL-WD adds **U+FEFF** to that pre-scan. If the decoded text contains U+FEFF **anywhere** (leading BOM, inside a comment, inside a quoted value, mid-line), the result is `(True, [])` before any line is processed. The coder may add U+FEFF to the existing frozenset under a new name (for example `_PRESCAN_REJECT`) or keep a second check. Either way, the check must run in the same place as AR-AL-4, so it covers the path function and both pinned reads. Both reads already decode with strict `"utf-8"`, not `"utf-8-sig"`, so a BOM survives decoding as U+FEFF and reaches this check. The coder must not change either decode to `utf-8-sig`. *Why reject and not strip:* PyYAML strips one leading BOM, and a YAML 1.2 loader may treat a BOM in the middle of the text as content. Rejecting the character is the only treatment that agrees with both parsers. This is the same reasoning as AR-AL-4.

**AL-WD-2. Outside-line grammar (the complete allowlist).** An outside line that is not L-blank or L-comment (those are classified first, exactly as today, and skipped) is canonical only if it is one of these forms:
- **O-marker:** the single leading document marker that SR-2 with AR-SR-2 already allows: `---`, optionally followed by ASCII whitespace and a comment, before any content line. Every other marker line → True (SR-2(c), unchanged).
- **O-steps:** the canonical top-level `steps:` line, fullmatching `steps:END` (`_STEPS_LINE_RE`). SR-2 still governs every other `steps` spelling, see AL-WD-4.
- **O-open:** `KEY:END` at column 0, with the same `KEY` and `END` as AL-1. The key has an **empty** value. It is the only line that may be followed by O-nested lines (AL-WD-3). If no O-nested line follows, YAML reads the value as null, which is allowed.
- **O-top:** `KEY: +VALUE END` at column 0. The coder must classify it with `_classify_steps_line(line)`: the line is O-top only if that call returns kind `key` with indent 0. So `VALUE` is the AL-2 per-key grammar. A top-level key named `id` or `human_gate_required` is held to the `VALUE(id)` / `VALUE(human_gate_required)` grammar. That is stricter than necessary and accepted, because such a key outside `steps:` has no meaning. Every other key uses `VALUE(other key)`: `PLAIN`, a closed `DQ` without a backslash, a closed `SQ`, or a one-line `FLOW` list of plain tokens.
- **O-nested:** see AL-WD-3.

Any other outside line → **`(True, [])`**, which ends the whole scan. That covers, among others:
- a column-0 line whose key is not `KEY` (`~: 1`, `}: 1`, `1: x`, `a.b: x`, a non-ASCII or NBSP-led key);
- a column-0 `- …` line outside the block (a top-level sequence);
- a `%` directive;
- a value that opens a multi-line construct: an unclosed `"`/`'`, `|`, `>`, `{`, or an unclosed `[`;
- a value containing `: ` or a URL in plain form (`PLAIN` has no `:`);
- `key:value` with no space after the colon;
- tags, anchors, aliases and explicit keys.

The return value is `(True, [])`, which matches how today's outside-line failures already return. An outside line is rejected before the block's ids are final, and once the result is True the ids are not used (AR-AM4-2 reads them only on the `None` path).

**AL-WD-3. Indented lines outside the block (replaces "an indented continuation of an allowed value" in the ruling's option text).** The AL rules allow **no** continuation of any value: AL-3 rejects every deeper line, and AL-2 values cannot start a multi-line construct. So the only indented outside form this design allows is a **one-level nested block mapping** directly under an O-open line:
- **O-nested:** `_classify_steps_line(line)` returns kind `key` with indent `n ≥ 1`. That is, `n` U+0020 characters, then `KEY: +VALUE END` under the AL-2 per-key grammar. The value must not be empty, so there is no second level of nesting.
- An O-nested line is canonical only if the most recent column-0 content line (O-open, O-top or O-steps; blank and comment lines do not count) was an **O-open**. The first O-nested line under that parent sets `nested_indent = n`. Every later O-nested line under the same parent must have exactly `n`. The next column-0 content line closes the parent and clears `nested_indent`.
- Every other indented outside line → `(True, [])`:
  - an indented line under an O-top or O-steps parent (a plain-scalar continuation or a block value);
  - a sibling at a different indent;
  - a deeper line (second-level nesting, or a continuation of a nested value);
  - an indented `- …` (a nested block sequence);
  - a tab-indented or NBSP-indented line (tab at the start is never L-blank or L-comment here unless the whole line is blank or a comment, which is classified first);
  - any indented line before the first column-0 content line (AL-WD-5).
- An indented line **inside** the steps block is still governed only by the in-block rules. AR-AL-1's block-end rule is unchanged. After `steps:`, a line starting with U+0020 stays in the block, so the steps key is never an O-open parent.

*Why this form is needed.* `contract/step-manifest.template.yaml` has a top-level `role_mappings:` (an O-open line) followed by a one-level nested mapping (`  code-review:    code-reviewer`, `  architecture:   architect           # …`). The ruling requires the template to keep scanning False/False/True. A grammar that allowed only column-0 single-line keys outside the block would gate every step of the template. This is the one place where the design reads the option text as needing a refinement. It is flagged under "Ambiguities resolved" below.

*A nested key named `steps`.* `a:` followed by `  steps: 1` is an O-nested line. YAML reads it as `a.steps` and not as the top-level key, so it must not count toward SR-2 (`test_g21_an_indented_steps_word_outside_the_block_is_not_a_second_steps_key` stays False). Today `_is_steps_key_line` is only consulted for column-0 lines, and that must stay so.

**AL-WD-4. Second, indented and BOM `steps` keys.**
- **A second column-0 `steps` key, or a non-canonical column-0 spelling of it** (`"steps":`, `'steps':`, `steps :`, `? steps`, `steps:[…]`, `steps: x`): SR-2 with AR-SR-2 is unchanged and is checked **before** the O-open/O-top classification. The column-0 line runs through `_is_steps_key_line` first. If that returns True, the line must be the first such key and must fullmatch `_STEPS_LINE_RE`, otherwise `(True, [])`. So the AL-1 `KEY` grammar, which accepts `"steps"`, can never classify a quoted steps key as an ordinary O-top or O-open line.
- **An indented `steps:` line:** it is O-nested under an O-open parent (harmless, see above). In every other position it is rejected by AL-WD-3 or AL-WD-5. In F1 the first content line is indented, so the scan gives `(True, [])` at line 1.
- **A BOM-prefixed `steps:` line:** AL-WD-1 gives `(True, [])` before any line is read. Even without AL-WD-1, the line would fail AL-WD-2, because its first character is not in `KEY`. The two rules overlap on purpose.
- **An escaped or tagged column-0 `steps` key** (`"st\x65ps":`, `!!str steps:`): `_bad_quoted_span` and the `!`/`?` checks (AR-AL-2) still fire first. Even without them, AL-WD-2 now rejects the line, because `KEY` has no escapes, tags or explicit-key forms.

**AL-WD-5. Indented first content line.** Take the first line that is not L-blank, not L-comment and not the allowed O-marker. If it starts with U+0020 or U+0009, the result is `(True, [])`. This rule is stated separately because the ruling names it. It is also implied by AL-WD-3, since no O-open parent exists yet. The coder implements it as an explicit check (for example `not content_seen and line.startswith((" ", "\t"))`), so a later refactor of AL-WD-3 cannot drop it. A first content line that starts with any other non-`KEY` character, such as NBSP or U+3000, fails AL-WD-2.

**AL-WD-6. Order of checks for an outside line, and why the grammar is complete.** `_manifest_scan` handles each outside line in this order. The first rule that fires returns `(True, [])`, except where a rule says it continues.
1. L-blank or L-comment → skip (unchanged; classified before the in-block test, AR-AL-1).
2. The global merge-key and anchor/alias net (unchanged).
3. The SR-3 (a)–(d) net: `_bad_quoted_span`, a `!` start or a `?` start on the body (unchanged, AR-AL-2). These are now redundant with AL-WD-2 and stay as defence in depth. Their T-G21 direct tests stay.
4. The line starts with U+0020 or U+0009:
   - AL-WD-5 if no content line has been seen;
   - otherwise AL-WD-3, then continue to the next line.
5. A document marker → SR-2(c) (unchanged). The allowed leading `---` continues to the next line.
6. Set `content_seen`. Close any open parent and clear `nested_indent`.
7. `_is_steps_key_line(line)` → SR-2 (a)/(b) (unchanged). The canonical first `steps:` line enters the block and continues to the next line.
8. O-open → open a parent and continue.
9. O-top → continue.
10. Anything else → `(True, [])`.

*Completeness argument (for the architect and for security).* When every outside line is canonical:
- every column-0 content line is a complete top-level `key: value` pair, or a `key:` whose nested lines are complete one-line pairs;
- no value can begin a construct that spans lines: there is no open quote, no `|`/`>`, no open flow and no plain continuation, because a deeper line under a non-empty value is rejected;
- after AL-WD-1, there is no BOM or ambiguous line break.

So PyYAML's top-level mapping keys are exactly the scanner's column-0 keys. The only top-level `steps` key YAML can see is the one SR-2 admitted, and its block is read only under the in-block allowlist that SR-AL already proved never looser. The same holds under a YAML 1.2 loader: every accepted form is read identically by YAML 1.1 and 1.2 (ASCII keys, single-line closed scalars, flow lists of plain tokens, comments, and space/tab whitespace), and the forms on which the versions disagree are rejected (AL-WD-1, AR-AL-4, AL-2's YAML 1.1 reserved words for ids).

**AL-WD-7. How AL-WD composes with the existing rules.**

| Rule | Effect of AL-WD |
|---|---|
| SR-1 (duplicate key in one item) | Unchanged; in-block only. Duplicate top-level non-`steps` keys, and duplicate O-nested keys, are **not** checked. Neither can change which `steps` value YAML reads, and duplicate `steps` keys are SR-2's. |
| SR-2 (a)/(b)/(c) | Unchanged and checked first for column-0 lines (AL-WD-6 steps 5 and 7). |
| SR-3 (a)–(d) | Kept as a redundant net on every outside line (AL-WD-6 step 3). |
| SR-3 (e)/(f), SR-5, AL-3, `raw_hgr` | Unchanged; in-block only. |
| AL-4 (non-ASCII) | Now document-wide. Outside lines may carry non-ASCII only in comment text and inside a closed `DQ`/`SQ` value of an O-top or O-nested key. That follows from reusing `_classify_steps_line`. |
| AR-AL-1 (block end) | Unchanged. The line that ends the block is now also held to AL-WD-2, so `~: 1` or `}: 1` after the block gives True. |
| AR-AL-4 (ambiguous line breaks) | Already whole-text (verified at `suspension_manager.py:1111`). Extended with U+FEFF (AL-WD-1). |
| AR-AM4-1 (`None` only if a block was entered), AR-AM4-2 (default-read token check), D-22 | Unchanged. |
| T-G10 (path function equals the scan, `None` → True) | Holds, because AL-WD lives entirely in `_manifest_scan`. |

**AL-WD-8. Consumer consequence (disclosed in the PR's human summary).** A consumer `contract/step-manifest.yaml` that uses any of the following **anywhere** in the file, not only under `steps:`, now has every step counted as human-gated for the dep-mapper LOW suspension:
- a multi-line value, a block scalar (`|`, `>`), or a quoted value that spans lines;
- a nested block list or more than one level of nesting;
- an unquoted value containing `: `, such as a bare URL;
- a key that is not `[A-Za-z_][A-Za-z0-9_-]*`;
- an indented first line;
- a byte-order mark.

This is fail-closed, the D-7 direction. The remedy is to quote such values on one line, write lists in flow form, and keep the top level to `key: value` lines plus one-level mappings like the template's `role_mappings`. As AR-AL-3 established, the gate is on `main` only and absent from `v0.6.0`, so no released consumer regresses. The canonical template is unaffected (AL-WD-9). Nothing else reads this scan.

**AL-WD-9. Canonical template check.** Technical-design read `contract/step-manifest.template.yaml` byte for byte (`cat -A`) and ran a prototype of AL-WD-1 to AL-WD-6 against it. Every outside line classifies:
- **L-comment:** the header comments, including the U+2014, U+2192 and U+00A7 characters inside them, the commented-out `# infra:` and similar lines, and the column-38 `# external integrations…` comment;
- **L-blank:** the blank lines;
- **O-top:** `contract_version: "1"` and `project: "[PROJECT NAME]"`, both closed `DQ` values;
- **O-open:** `role_mappings:`;
- **O-nested:** its seven nested lines at indent 2, including `architecture:   architect           # …`, which is `PLAIN` followed by `END`;
- **O-steps:** `steps:`.

The steps block is unchanged from SR-AL. The prototype gives steps `1`, `2` and `3` → False, False and True. **The template is not edited by AL-WD.** Its AR-AL-3 comment line stays as it is, and T-G24's text assertion is unaffected.

**AL-WD-10 (agy L1). Every intermediate component of the working-tree path must be a real directory.** G4 (§5.2.2 item 3, as amended by SR-4) currently calls `os.lstat` only on `Path(toplevel) / _STEP_MANIFEST_PATH`. That follows a symlinked `contract/` directory. The rule: after the toplevel is resolved (E-G5 checks unchanged) and **before** the final-component `lstat`, G4 calls `os.lstat` on each intermediate component of `_STEP_MANIFEST_PATH` under `toplevel`, in order. Today that is only `toplevel / "contract"`. The coder derives the list from `Path(_STEP_MANIFEST_PATH).parent.parts`, so a future path change keeps the rule. **[AR-WD-1]** "Each intermediate component" means each **cumulative prefix** path, outermost first: for parts `p1, p2, …, pk` of `Path(_STEP_MANIFEST_PATH).parent.parts`, G4 lstats `toplevel/p1`, then `toplevel/p1/p2`, …, then `toplevel/p1/…/pk`. It never lstats a bare part name joined directly onto `toplevel` after the first. The first prefix that fails any bullet below decides the result, and no later prefix or the final component is examined.
- `FileNotFoundError` → the working-tree manifest is **absent**. G4 skips the remaining lstats and the read, and compares `None` against `head["blob"]` exactly as today: both absent → consistent; present at head → E-G2 `deleted`.
- Any other `OSError` → E-G2 `unreadable: <strerror>` (the existing detail).
- The mode is not `S_ISDIR` (a symlink to a directory, a symlink to anything else, a regular file, a FIFO) → E-G2 `not a regular file`. This reuses the existing detail, so the E-G2 detail set stays closed. The message is literally about the manifest path, which is not a regular file at a real path.

This is consistent with the existing final-component rule. It is **not** a bypass today, because the bytes must still equal the head blob and the flag comes from the pinned blobs. It restores G4's structural guarantee. The existing `test_working_tree_lstat_oserror_is_a_mismatch` and `test_g18_rev_parse_runs_after_the_head_read_and_before_lstat` fakes filter on a `MANIFEST_PATH` suffix, so they are unaffected by the extra `lstat`. Both must pass unchanged. *Residual:* a swap of `contract/` between the `lstat` and the read is a deliberate local race. It falls under R-5. The coder does not need `O_NOFOLLOW`/`openat`.

**AL-WD-11 (agy L2). The real-manifest test takes step ids from the oracle.** `test_g24_real_manifest_if_present_is_never_looser_than_yaml` currently iterates `sm._manifest_scan(text, STEP)[1]`, the ids from the scanner under test, so a scanner that drops an id escapes the check. The rule:
- Add a test helper `_oracle_step_ids(text) -> set[str]`. It returns `{str(item.get("id")) for item in steps if isinstance(item, dict) and "id" in item}` when `yaml.safe_load(text)` succeeds and gives a dict whose `steps` is a list. Otherwise it returns `set()`.
- Add a helper `_assert_never_looser(text)`. For every id in `_oracle_step_ids(text) | set(sm._manifest_scan(text, STEP)[1])` where `_yaml_says_gated(text, id)` holds, it asserts `sm._manifest_gate_scan(text, id) is True`.
- `test_g24_real_manifest_if_present_is_never_looser_than_yaml` calls `_assert_never_looser(text)`. It still returns early when the file is absent, because this repo has none (T-G7).
- The helper is exercised in CI by T-G33 and T-G34, so the absent-file early return does not leave it untested.

**Tests (AL-WD).** All new fixtures go into module-level collections and are added to `_G19_TEXTS`. `G19_ACCEPTED_FLOOR` and `G19_GATED_FLOOR` are raised to the newly observed counts (T-G19 round 3 rule: observed minus nothing). PyYAML is imported unconditionally (AR-SR-3). Every "True" assertion checks the exact `(True, [])` where the rule is an outside-line or pre-scan rejection.
- **T-G27 (F1 and F2 regressions, verbatim).** Use the two texts above exactly, with step `s1`.
  - Assert `_yaml_says_gated(text, "s1")` is True for both, so the fixture stays meaningful.
  - Assert `sm._manifest_scan(text, "s1") == (True, [])` for both.
  - Assert the path function gives True.
  - Assert `read_manifest_gate_at` gives `flag=True, error=None` at head (`unlisted_step=True`) and at the default SHA (`unlisted_step=False`).
  - End to end: the default branch commits F1 and head commits canonical `s1: false` → effective `{"flag": True, "error": None}`. The same with F2.
- **T-G28 (AL-WD-1 and AL-WD-5).**
  - True, each `(True, [])`:
    - U+FEFF as the first character of an otherwise canonical `MANIFEST_FALSE`;
    - U+FEFF inside a comment;
    - U+FEFF inside a closed `DQ` value of `name`;
    - U+FEFF at the end of a top-level line;
    - an otherwise canonical manifest with every line indented by 2 spaces, and by 4;
    - a first content line indented with one tab;
    - the same indented document after a leading `---`;
    - the same after leading comment and blank lines.
  - Controls, unchanged: a leading `---` followed by canonical column-0 content → `(False, ["s1"])`; column-0 content after indented comment lines → `(False, ["s1"])`.
- **T-G29 (AL-WD-2 and AL-WD-3 rejections).** Each fixture is a canonical `MANIFEST_FALSE` with one outside construct added, once **before** the `steps:` line and once **after** the block. Each must give `(True, [])`:
  - `foo: |` + `  text`
  - `foo: >-` + `  text`
  - `foo: "a` + `b"`
  - `foo: 'a` + `b'`
  - `foo: a` + `  b` (plain continuation)
  - `foo:` + `  - a` (nested block list)
  - `foo:` + `  a:` + `    b: c` (two levels)
  - `foo:` + `  a: 1` + `   b: 2` (sibling indent mismatch)
  - `foo: 1` + `  a: 2` (indented line under O-top)
  - `foo: {a: 1}`
  - `foo: [a, b` (unclosed flow)
  - `url: https://x.example`
  - `foo:bar`
  - `1: x`
  - `a.b: x`
  - `~: 1`
  - `}: 1`
  - `- x` at column 0
  - `%YAML 1.2` before the content
  - `foo:` + `\ta: 1` (tab-indented nested line)
  - `foo:` + `  a: 1` (NBSP-indented nested line)
  - ` foo: 1` (NBSP-led column-0 key)
  - `foo: "a\\b"` (DQ with a backslash)
  - `foo: !x y`
- **T-G30 (controls that must stay False, so AL-WD is not just failing closed).** Each gives `(False, ["s1"])` for step `s1`:
  - `role_mappings:` + two nested `k: v` lines, placed before `steps:`;
  - the same placed after the block;
  - an O-open with no nested lines (YAML null);
  - nested lines with an interleaved column-0 comment and blank line;
  - `a:` + `  steps: 1` (the existing T-G21 case, kept);
  - `name: "a — b"` and `name: 'it''s'` at top level;
  - `list: [a, b]` at top level;
  - `x: 1 # &x *x <<: y` (the existing trailing-comment net case);
  - `foo: ` with trailing spaces (O-open).
  - **Template:** `_manifest_gate_scan` on `contract/step-manifest.template.yaml` for steps `1`, `2` and `3` → False, False and True, through the path function and through both pinned reads with the template committed as default and head. This reuses T-G24's fixture and adds the pinned reads for step `2`.
- **T-G31 (direct unit tests of the outside classification).** If the coder adds a helper (suggested: `_classify_outside_line(line) -> tuple[str, int, str | None] | None`, returning kind `open`, `top` or `nested`), test it with one case per accepted form and one case per rejection from T-G29, in isolation, the same way T-G21 tests `_classify_steps_line`. If the coder inlines the classification in `_manifest_scan`, T-G29 and T-G30 cover it and T-G31 is not required. The choice must be stated in the coder's self-flag.
- **T-G32 (AL-WD-10, L1).** In the `repo` fixture, with the same manifest committed at default and head:
  - `contract` replaced by a symlink to a directory holding a byte-identical `step-manifest.yaml` → `{"flag": True, "error": <E-G2 prefix> + "not a regular file"}`;
  - `contract` replaced by a regular file → the same E-G2 `not a regular file`;
  - `os.lstat` faked to raise `PermissionError(13)` only for the `contract` component → E-G2 `unreadable: Permission denied`;
  - `contract` removed entirely while head has the manifest → E-G2 `deleted`;
  - `contract` removed while the manifest is absent at both SHAs → `{"flag": False, "error": None}`.
  - Control: a real `contract/` directory with a matching file → unchanged result.
- **T-G33 (AL-WD-11, L2).**
  - `_oracle_step_ids(F1) == {"s1"}`, while `sm._manifest_scan(F1, "s1")[1] == []`. This shows why the scanner's ids are the wrong source.
  - `_assert_never_looser` passes on F1, F2 and the template.
  - A monkeypatched `sm._manifest_scan` that returns `(False, [])` on F1 makes `_assert_never_looser(F1)` raise `AssertionError`. This is the mutant the old test would have missed.
  - `test_g24_real_manifest_if_present_is_never_looser_than_yaml` uses the helper.
- **T-G34 (whole-document never-looser property).** For every text in `_G19_TEXTS`, call `_assert_never_looser(text)`. That checks every oracle id, not only the paired step. Add a generated family to `_G19_TEXTS`: for each of `MANIFEST_FALSE`, the G21B repro and the template, apply each of these transforms:
  - (a) indent every line by 2;
  - (b) prefix U+FEFF;
  - (c) insert before `steps:` a top-level `foo: "x` value whose continuation lines hold a decoy `steps:` block with `false`, closed by `x"` (the F1/F2 shape, without the indent or BOM);
  - (d) the same decoy in a `foo: |` block scalar, placed after the real block;
  - (e) the same decoy in a plain multi-line value `foo: x` followed by indented lines.

  Each transformed text whose real block is gated must scan True. Assert a floor on how many of the generated texts PyYAML accepts with the oracle firing, so the family cannot silently go vacuous.
- **Existing test amended.** `test_g21_block_ends_at_every_ascii_printable_first_char_except_dash_and_hash` keeps `X`, `z` and `A` (now also `_`) with the "result unchanged" assertion. Its `~` and `}` cases move to a new parametrised assertion `== (True, [])`. Under AL-WD they are not `KEY` characters. The prototype run of the whole `test_suspension_timebox.py` file against AL-WD failed on exactly these two parameters and on nothing else. Every `test_manifest_*` test still passes unchanged (T-G10).

**Docstrings (extends SR-6).** These are checked at code review.
- The `manifest_human_gate_required` and `_manifest_scan` docstrings replace their "Outside the block" paragraph with the AL-WD grammar: the O-forms, the one-level nested mapping, the indented-first-line rule, and U+FEFF in the pre-scan list.
- The "Accepted false positives: the scanner does not track block scalars outside the block…" sentence is replaced. Any block scalar or multi-line value anywhere in the file now gates by rule, so it is no longer an incidental false positive.
- The remedy sentence becomes whole-file: single-line values everywhere, lists in flow form, top-level nesting at most one level.
- The `effective_manifest_human_gate` docstring adds that every intermediate path component must be a real directory (AL-WD-10).

**Build files.** No new file. §9 row 1 (`suspension_manager.py`: `_manifest_scan`, the pre-scan set, the optional outside-line helper, G4 in `effective_manifest_human_gate`, and the docstrings) and row 3 (`test_suspension_timebox.py`: T-G27 to T-G34, the T-G21 amendment, and the L2 helpers). The template is **not** edited (AL-WD-9). Stdlib only: no runtime PyYAML ([ARCH-AM4-SR] proportionality, unchanged).

**Ambiguities resolved (for the architect's fidelity check).**
1. *"An indented continuation of a flow or plain value already allowed by the AL rules".* The AL rules allow no continuation lines at all, so read literally this clause admits nothing. But the template's `role_mappings:` is a one-level nested block mapping, and the ruling requires the template to stay False/False/True. AL-WD-3 therefore allows exactly one indented form: a one-level nested mapping of AL-2-grammar `KEY: VALUE` lines under an empty-valued column-0 key, at one consistent indent. It allows no plain or flow continuation. This is the narrowest reading that keeps the template unchanged. The completeness argument (AL-WD-6) covers it.
2. *"(True, ids)".* Outside-line and pre-scan rejections return `(True, [])`. That matches the existing code's convention for line-level failures, documented in the `_manifest_scan` docstring. The ids are unused whenever the result is True.
3. *Template comment.* The AR-AL-3 comment line names step entries only. AL-WD extends the rule to the whole file, but the template's own top-level content is already canonical. The design does **not** edit `contract/step-manifest.template.yaml` (no extra protected-surface diff). The remedy is carried by the docstrings and the PR's human summary (AL-WD-8). If the architect wants the comment widened, that is a one-line `contract/**` edit, and T-G24's text assertion would need its wording updated to match.
4. *AR-AL-4 scope.* The task asked whether AR-AL-4 already applies document-wide. It does: a whole-text contains check at `suspension_manager.py:1111`, before line processing. AL-WD only adds U+FEFF.
5. *L1 error detail.* It reuses E-G2 `not a regular file`, not a new detail string, so the E-G2 detail set and the reliability-reviewed message surface are unchanged.

*Startup gap and affected sign-offs (AL-WD).* Yes, this should have been settled earlier. The convergence condition in [ARCH-AM4-SR] scoped the allowlist to "inside `steps:`", while the threat (a decoy block hidden in an outside value) was document-wide. Annotate #2214's `startup-artifact-gap`.
- **Orphaned and must re-review the AL-WD delta:**
  - code-review, for `_manifest_scan`, the optional helper, G4 and the docstrings;
  - security, which must re-run `probe2392sr.py` and `fuzz2392sr.py` extended with the T-G34 transforms (indent, BOM, outside multi-line decoys) and record zero looser-than-PyYAML cases; **[AR-WD-2]** the extended fuzz must include a **structured** generator: a real steps block whose target item is gated, with random outside fragments before and after it (decoy blocks inside multi-line values, one-level and two-level nested mappings, indented `steps:` keys, plain continuations, comments and blank lines at mixed indents) and an optional whole-document indent. Security records the count of PyYAML-accepted, oracle-gated documents, which must be at least 10 000, alongside the zero looser count. The unstructured run alone (21 gated documents) is not sufficient evidence for sign-off;
  - test-unit, for T-G27 to T-G34 and the oracle helpers.
- **Not affected:** reliability (no new message text: L1 reuses E-G2 details, and E-G5 is untouched). All other AM-1 to AM-4 and SR sign-offs stand.
- **Second review:** re-runs on the AL-WD delta, then FINAL runs full-range, per the ruling's "one coder round plus a second review".
- **Escalation:** if that second review finds another scanner-looser-than-parser case, it goes to the human again, per [ARCH-AM4-SR round 5]. No agent rules on it.

**Human Review Required (AL-WD).** No new human ruling is needed: this implements ruling A. The human should notice two things at merge:
- the AL-WD-8 consumer consequence, which is the safe direction;
- the AL-WD-3 refinement, which allows the template's one-level `role_mappings` mapping. Without it, the ruling's own template constraint could not hold.

**[ARCH-AM4-WD] Architect ruling (2026-11-25): APPROVED with required changes AR-WD-1 and AR-WD-2 (applied inline).** This is a ruling-implementation fidelity review, not a sixth SR round. The SR loop stays closed at round 5 of 5.

*Fidelity to human ruling A.* The amendment implements the ruling as given and does not contradict it.
- "Extend the canonical-line allowlist to the whole document": AL-WD-2 turns the outside-line denylist into a closed allowlist. It has five forms (O-marker, O-steps, O-open, O-top, O-nested), and any other line gives `(True, [])`. The in-block rules are untouched.
- "Gate any indented first line": AL-WD-5 does this as an explicit check, separate from AL-WD-3, so a refactor cannot drop it.
- "Gate any BOM": AL-WD-1 rejects U+FEFF anywhere, not only at the start of the text.
- "By construction rather than case by case": the AL-WD-6 completeness argument is structural, not a list of patched shapes.
- "Fails toward gated": every new rule can only add True.

*AL-WD-3, the one indented form. It is within the ruling's intent and it is safe.* Read literally, "an indented continuation of a flow or plain value already allowed by AL rules" admits nothing, because no AL value has a continuation. But the template has been a binding constraint (False/False/True) in every prior round, and the human did not lift it. A ruling that gated the canonical template would gate every consumer who copied it. So the narrowest form that keeps the template is the correct reading. The design does not widen the allowlist beyond what the template needs: one level, single-line AL-2 values, one indent per parent, and only under an empty-valued column-0 key. I checked whether that form can hide a `steps` key or be read differently by YAML:
- **The root indent is pinned to 0.** AL-WD-5 makes the first content line column 0, so the root mapping is at indent 0. Every indented line is then a child of the preceding column-0 key in YAML, never a top-level key. An indented `steps:` is `parent.steps` (T-G21 case kept).
- **No construct can span from a nested line to a later line.** Each nested value is a complete single-line AL-2 scalar or flow list. A deeper line is rejected by the exact-`n` rule. A shallower indented line is rejected by the same rule. A column-0 line is outside the plain scalar's continuation indent (column 0 < n+1), so YAML starts a new top-level key there, and the scanner treats it as one.
- **Nested block sequences, second-level mappings and tab or NBSP indents are all rejected**, so YAML's compact-sequence and indentation rules never come into play.
- **The parent cannot be `steps`.** The column-0 `steps` line enters the block. Every other spelling of a top-level `steps` key is caught by `_is_steps_key_line` before O-open is tried (AL-WD-4). The `KEY` grammar admits only plain, `"…"` and `'…'` forms of `[A-Za-z_][A-Za-z0-9_-]*`, and `_is_steps_key_line` normalises all three.
- **YAML 1.1 and 1.2 agree.** A one-level block mapping of ASCII keys and single-line closed scalars is read identically by both.

*Independent prototype (architect).* I implemented AL-WD-1 to AL-WD-6 on top of the current `_classify_steps_line` and ran it against the repo venv's PyYAML:
- The template gives `1, 2, 3` → False, False, True.
- F1 and F2 verbatim give `(True, [])`.
- The unstructured random-fragment fuzz gave 0 looser cases, but only 21 documents were gated. That matches technical-design's caveat.
- A structured fuzz gave 41 620 PyYAML-accepted documents in which `s1` is gated, and 0 looser cases. Each document was a real gated `s1` block with 0 to 6 random outside fragments on each side (decoy `steps:` blocks inside quoted, block and plain multi-line values, nested mappings at mixed indents, indented `steps:`, `id:` and flag keys, comments, markers) and an optional 2-space whole-document indent. AR-WD-2 makes this kind of generator part of security's sign-off evidence.

*The other choices.*
- **`(True, [])` on rejection: correct.** In `read_manifest_gate_at` the ids are consulted only when the flag is `None`. Every True short-circuits, so an empty id list cannot change a result. It also matches the existing in-block and AR-AL-4 convention. T-G27's default-read assertion (`unlisted_step=False` → `flag=True`) pins this.
- **U+FEFF in the AR-AL-4 whole-text check: correct, and the right place.** The pre-scan covers the path function and both pinned reads. Rejecting is the only treatment that agrees with a PyYAML loader, which strips one leading BOM, and a YAML 1.2 loader, which may keep a BOM mid-text as content. The prohibition on `utf-8-sig` is load-bearing and must stay in the docstring.
- **L1 reusing E-G2 `not a regular file`: accepted.** The E-G2 detail set stays closed, and reliability's sign-off stands. The message is still true: the manifest path does not resolve to a regular file through real directories. AR-WD-1 only fixes the precision of "each intermediate component", because a literal reading could have a coder lstat bare part names under `toplevel`.
- **L2 oracle ids: correct.** T-G33's monkeypatched mutant proves the old test's blind spot is closed.
- **The template comment left unchanged: accepted.** The line sits directly above `steps:` and states the rule for step entries, which is where consumers will hit it. Under AL-WD its "nested" wording means more than one level, which is still accurate in context. Widening it would add a second protected-surface `contract/**` diff and a T-G24 wording change to a ruling whose cost the human fixed at "one coder round plus a second review". The whole-file remedy is carried by the docstrings and the PR's human summary (AL-WD-8). This is the right trade.
- **The AL-WD-7 decision not to check duplicate top-level and nested non-`steps` keys: accepted.** Neither can change which `steps` value a last-wins parser reads. A duplicate-rejecting parser errors, which is never looser.

*Required changes (applied inline).*
- **AR-WD-1 (AL-WD-10 precision).** The intermediate lstats run on cumulative prefix paths, outermost first, and the first failing prefix decides the result.
- **AR-WD-2 (sign-off evidence).** Security's extended fuzz must include a structured generator and record at least 10 000 PyYAML-accepted, oracle-gated documents with 0 looser cases. An unstructured run with a handful of gated documents does not count as evidence of "never looser".

Neither item changes the grammar, a test expectation or the template, so neither needs another design round.

*Product boundary.* There is no new user-visible behaviour beyond the AL-WD-8 fail-closed consequence, which the human ruling already accepted ("fails toward gated"). There is no cost, retention, topology or operational consequence. No further checkpoint is needed.

*Startup gap and sign-offs.* I concur with the AL-WD analysis. The SR convergence condition I set scoped the allowlist to the block while the threat was document-wide. That was my error, and the `startup-artifact-gap` annotation on #2214 is correct. Code-review, security (with AR-WD-2) and test-unit re-review the AL-WD delta. Reliability stands. The second review runs on the delta, then FINAL runs full-range. Any further scanner-looser-than-parser finding goes to the human on record, per [ARCH-AM4-SR round 5]. No agent rules on it.

The coder may implement AL-WD-0 to AL-WD-11, with AR-WD-1 and AR-WD-2.

**Callers.**
- `cmd_check_suspended_resolutions`: see the CLI paragraph above. `eff = effective_manifest_human_gate(step, head, main)` runs only inside the `suspension_applies` branch, after `main = read_default_branch_suspension()`.
- `pr_readiness` REQ-W-18: see §5.4.
- `oversight-evaluator.md` **is not changed.** Its 7b(ii) prose (line 131) still passes `--human-gate-required {manifest human_gate_required}`. That value, read by the evaluator from whatever it sees, is only a floor. The CLI now owns the pinned read, so a tampered working tree that misleads the evaluator into passing `false` is still caught by G4, and a committed loosening is still caught by G5. The evaluator file is a protected surface, and AM-4 does not need to touch it.

### 5.3 Disclosure in the PR body

- **Who writes it:** `oversight-orchestrator`. It writes the section below into `.claudetmp/oversight/step{N}-handoff.md`, which is the PR body, whenever the risk assessment has a `suspended: dep-mapper` resolution.
- **Where it goes [AM-1, D-20]:** directly after the `## 🤖 AI-Submitted Pull Request` block, which stays the first section. The section goes immediately before the first line starting `# ` (the `# Handoff — Step {N}` line), or, if the handoff has no such line, before the next col-0 ATX heading after the AI-Submitted block. It is not appended at the end. Leave one blank line before the disclosure heading (P9) and one blank line after `Result: PASS` (R7). Then the only lines before it are the fixed AI-Submitted template, and P7–P9 check that this is so. With this placement, the AI-Submitted blocks of all 61 existing handoffs pass P0–P5. 52 of the 61 also pass P7. The other 9 are older or escalated handoffs that opened no PR, and they would fail closed. If the section is appended at the end, 4 of the 61 fail P1/P3.
- **Who checks it:** `pr_readiness` REQ-W-18 (§5.4), deterministically, before the PR can be opened.
- **Why the evaluator cannot check it:** the evaluator runs before the handoff exists, so its check runs without `--require-disclosure`.

Required section:

```markdown
## dep-mapper LOW disclosure (suspended blocker)

dep-mapper reported Data confidence: LOW on this step. Per contract/gate-suspension.md
(Authorized by: <the file's "Authorized by:" value>; expires: <EXPIRES or none>; until-closed: <issue UNTIL_CLOSED, e.g. issue 2162, or none>)
it is not blocking while the suspension is active.
Manual trace: .claudetmp/oversight/step{N}-dep-mapper-trace.md

<the trace's "## Callers / readers checked" heading, blank line and table, copied unchanged>

<the trace's "## Items dep-mapper left untraced" heading, blank line and list, copied unchanged>

Result: PASS

```

[AM-1] The `<…>` placeholders above are template notation. They are replaced and never written. The first prose line no longer wraps `Data confidence: LOW` in backticks, because R1 bans backticks. R5 requires a blank line or a section heading on each side of the copied table. The other blank lines are part of the template, so that `Result: PASS` renders as its own paragraph and is not lazily joined to the last bullet. The validator does not check them.

[ARCH-R1] The template is **generic**. `oversight-orchestrator.md` is a CORE agent shipped to consumers, so it must not hard-code this repo's issue numbers (#2174, #2214). The values come from `--suspension-status dep-mapper` (`EXPIRES=`, `UNTIL_CLOSED=`) and the file's `Authorized by:` line. The ruling's provenance is in the suspension file itself (§7).

**SPEC-82 WARN note (orchestrator) [ARCH-R1; per the worker direction on ESC-1].** When the evaluator's SPEC-82 WARN names `contract/gate-suspension.md`, the orchestrator keeps the WARN's conditional item **verbatim** and appends one sub-line under it. The sub-line gives a *verification recipe*, not an assertion that the WARN is benign: "To verify: `git log --diff-filter=A --format='%h %s' -- contract/gate-suspension.md` gives the adding PR (`(#<n>)`). Confirm that PR carries a CODEOWNER approval and that `git diff <default>...HEAD -- contract/gate-suspension.md` is empty on this branch." The orchestrator never removes, merges or rewords the WARN item, and never marks it resolved.

`validate_disclosure(handoff_text, step, trace_text, suspension_text)` checks six things. (#2349 added the last three comparisons; the original build only matched marker strings.)
1. The heading line `## dep-mapper LOW disclosure (suspended blocker)` is present **exactly once in the whole body** (prefix, section and suffix all count) [AM-1; ARCH-R2 AR2-7]. It must be at column 0, compared after removing trailing spaces only. An indented heading is not recognised. Zero matches → `disclosure heading missing: ## dep-mapper LOW disclosure (suspended blocker)`. More than one → `disclosure heading appears <n> times; exactly one is allowed`. Every later check needs the single heading, so on either error only this error is reported.
2. Its section starts on the line after the heading [AM-1]. It ends just before the next line matching `^#{1,6}( |$)` at column 0, other than the two copied trace headings (which pass through), or at EOF. That section contains each of these:
   - `Data confidence: LOW`
   - `contract/gate-suspension.md`
   - `dep_trace_path(step)`
   - a line starting `| Changed file`
   - a line matching `^Result:\s*PASS\s*$`
3. The disclosed callers table equals the validated trace's: same header, and the same data rows in the same order. An omitted, altered, extra or reordered row fails.
4. The heading `## Items dep-mapper left untraced` is in the section, and the non-blank lines under it, up to the closing `Result: PASS` line, equal the trace's non-blank Items lines exactly after whitespace normalisation: same order, same count, nothing extra. Errors: `disclosure missing the copied heading '## Items dep-mapper left untraced'`, `disclosure omits untraced item: <line>`, `disclosure has a line under '## Items dep-mapper left untraced' that is not in the trace: <line>` and `disclosed untraced items differ from the trace in order or count`.
5. The disclosure states `Authorized by: <value>` from the default-branch suspension file, and every `expires:` / `until-closed:` value it states equals the active suspension line's (`none` when the line has no such field). [AM-3] The disclosed until-closed value is matched with `until-closed:[ \t]*(issue[ \t]+(\d+)|none)(?![0-9A-Za-z])`, and the captured number is compared, as an integer, with the suspension line's `until-closed: #N` number. `none` must be written when the line has no `until-closed:`. The issue `#` stays in `contract/gate-suspension.md`, which is not a PR body. Errors:
   - **Old `#`/`GH-` form:** `until-closed:` followed by optional whitespace and then `#<digits>` or `GH-<digits>` → `disclosure writes until-closed as "#N"; GitHub's closing-keyword guard (scripts/automation/closing_keywords.py) reads "closed #N" as closing issue N, so write "until-closed: issue N"`. This is reported in addition to any mismatch error.
   - **Mismatch:** `disclosed until-closed [<values>] != suspension <want>`, where `<want>` is `issue N` or `none`. The format is unchanged; only the value form changed.
   - **Absent:** `disclosed until-closed absent != suspension <want>`.

   [AM-1; ARCH-R2 AR2-8] If the suspension file's value itself fails a section line rule that applies to its content (R1 or R4), this item reports the fail-closed error given under item 6, "Required values and forbidden characters".

6. **The section is visible text, checked by an allowlist [AM-1; D-19, D-20, D-21; #2349; ruling A on #2214].** This item replaces the earlier denylist: raw `]:` and `<[A-Za-z/?!]` anywhere in the body, link-residue stripping, and comment/fence stripping through `_visible_markdown`. The checks run on the **raw** text, and nothing is stripped first. The body has three parts:
   - the **prefix**, every line before the heading;
   - the **section** (item 2);
   - the **suffix**, everything after the section, which is not checked.

   Every line is checked, and the errors from all lines are collected (no stop at the first one). Within one section line, only the first rule it breaks is reported, in the order R1, R2, R3, R4. Each error names its 1-based line number `<k>` in the handoff, as the ops SHOULD_FIX on error messages asked.

   **R0. Line splitting.** First replace `\r\n`, then any lone `\r`, with `\n`. Then split on `\n` only. `str.splitlines()` must not be used for any check in this item. It also breaks lines on U+000B, U+000C, U+001C–U+001E, U+0085, U+2028 and U+2029, which CommonMark treats as ordinary characters, so the validator and GitHub would disagree about where lines start. The same splitting is used to locate the heading and the section (items 1–2) and the trace sections (items 3–4 and V9).

   **Prefix rules (P0–P9).** P0–P5 ban the constructs that can carry across a blank line or a col-0 ATX heading and swallow the section. P7–P9 enforce the D-20 premise that the prefix is the AI-Submitted template (D-20). P0–P5 and P8 check every prefix line. P7 checks line 1. P9 checks the line before the heading.
   - **P0.** The line contains no character in Unicode category Cc other than tab, and none of U+0085, U+2028, U+2029. Error: `disclosure prefix line <k>: control or line-separator character U+XXXX before the disclosure heading`.
   - **P1.** The line is not a fence line. Remove the leading container prefix: repeatedly, any run of spaces or tabs, then one of `>`, `-`/`*`/`+` followed by a space or tab, or `\d{1,9}` followed by `.` or `)` and a space or tab. If what remains starts with three backticks or `~~~`, the line is a fence line. This over-matches on purpose: it also catches indented-code lines and fences nested in a list item or blockquote. Error: `disclosure prefix line <k>: code fence before the disclosure heading (GitHub may render the disclosure as code, math or a diagram); place the disclosure section directly after the AI-Submitted block`.
   - **P2.** The line contains no `$` at all. This covers `$$` math blocks, inline math and `` $`…`$ ``. Banning a single `$` too costs nothing with the D-20 placement, and it does not depend on whether GitHub's math pairing respects block boundaries. Error: `disclosure prefix line <k>: "$" before the disclosure heading (GitHub math can hide the disclosure); place the disclosure section directly after the AI-Submitted block`.
   - **P3.** The line has no match for `<[A-Za-z/?!]`. This covers HTML blocks, `<details>` and `<!--`. Error: `disclosure prefix line <k>: raw HTML before the disclosure heading, which GitHub may hide or collapse; place the disclosure section directly after the AI-Submitted block`.
   - **P4.** The line does not contain `]:`. Error: `disclosure prefix line <k>: "]:" (link-reference definition) before the disclosure heading`.
   - **P5.** After every complete single-line plain inline link `(?<!!)\[[^\[\]\n]*\]\([^\s()<>"']*\)` is removed, the line contains none of `](`, `][`, `![`. Error: `disclosure prefix line <k>: link with a title, reference link or image before the disclosure heading`. P4 and P5 are defence in depth. By D-20 a definition or title cannot cross a col-0 heading, but both rules cost nothing.
   - **P6.** Retired, so the numbering stays stable [ARCH-R2 AR2-7]. The exactly-once rule counts over the whole body, so it lives under item 1.
   - **P7 [ARCH-R2 AR2-1].** Line 1 of the body, with trailing spaces removed, equals `## 🤖 AI-Submitted Pull Request`. This also rules out front matter, and a disclosure buried under arbitrary prefix content. Error: `disclosure prefix line 1: the PR body must start with "## 🤖 AI-Submitted Pull Request"`.
   - **P8 [ARCH-R2 AR2-1].** No prefix line other than line 1 matches `^#{1,6}( |$)`. Error: `disclosure prefix line <k>: heading before the disclosure heading; place the disclosure section directly after the AI-Submitted block`.
   - **P9 [ARCH-R2 AR2-1].** The line directly before the disclosure heading is blank after removing trailing spaces. Error: `disclosure prefix line <k>: the line before the disclosure heading must be blank`. P7 guarantees the prefix has at least one line, so this rule is always defined.

   **Section rules (R1–R7).** Every section line must be exactly one of the following kinds, or the error for the first rule it breaks is reported. Before classifying a line, remove its trailing spaces (U+0020). Trailing tabs are not removed, so R1 rejects them.
   - **Kind A, blank.** The line is empty after removing trailing spaces.
   - **Kind B, copied heading.** The line equals `## Callers / readers checked` or `## Items dep-mapper left untraced` (`_DISCLOSURE_COPIED_HEADINGS`). Each may appear at most once in the section, and Callers comes first. Error: `disclosure line <k>: copied heading "<h>" repeated or out of order`.
   - **Kind C, attribution literal.** The line equals `🤖 Generated with [Claude Code](https://claude.com/claude-code)` byte for byte. This matters only if a handoff still has the section at EOF. With the D-20 placement the attribution line is in the suffix.
   - **Kind D, table row.** The line starts with `|` at column 0. It must satisfy R1 and R5.
   - **Kind E, prose or bullet line.** Any other line. It must satisfy R1–R4.

   - **R1. Character set.** Every character of a Kind D or E line is in the allowed set:
     - ASCII letters, digits and space;
     - `. , : ; ( ) / - _ ' " ! ? = + % # @ { } ^`;
     - `—` (U+2014), `–` (U+2013), `→` (U+2192), `§` (U+00A7);
     - `|`, in Kind D only.

     Everything else is rejected, which means: `` ` ``, `$`, `\`, `&`, `[`, `]`, `<`, `>`, `*`, `~`, tab, every other non-ASCII code point (zero-width, bidi, NBSP, homoglyphs), and `|` outside a table row. Error: `disclosure line <k>: character "<c>" (U+XXXX) is not allowed in the disclosure section; allowed are letters, digits, spaces and . , : ; ( ) / - _ ' " ! ? = + % # @ { } ^ — – → §, plus "|" in table rows`.
   - **R2. Indentation (Kind E).** At most 3 leading spaces. Error: `disclosure line <k>: indented 4 or more spaces (GitHub renders it as code); use at most 3`.
   - **R3. Line start (Kind E) [ARCH-R2 AR2-6].** Remove the leading spaces (the trailing spaces are already gone). The rest is either:
     - **a bullet:** `- ` followed **immediately** by a start character; or
     - **plain text:** its first character is a start character.

     The start characters are `[A-Za-z0-9(./"']`, and none of them opens a block in CommonMark/GFM. So `-     x` is rejected, because a list item followed by 5 spaces opens indented code. A bare `-` is rejected too, because after a paragraph line it is a setext underline (a `- ` with only trailing spaces becomes `-` once they are removed). Empty bullets are therefore not allowed; write `- none`. This rule rejects headings (`#`), blockquotes and alerts (`>`), `*`/`+` lists, thematic breaks and setext underlines (`-`, `---`, `***`, `___`, `===`), fences, HTML and task items. Error: `disclosure line <k>: line must start with a letter, digit, "(", ".", "/" or a quote, or with "- " directly followed by one; found "<text up to 3 chars>"`.
   - **R4. Emoji shortcodes (Kind D and E) [ARCH-R2 AR2-8].** No match, **case-insensitively**, for `:[a-z0-9_+-]*[a-z_+-][a-z0-9_+-]*:`. That is a colon-delimited name with at least one character that is not a digit, which also catches `:+1:` and `:-1:`. GitHub replaces a known `:name:` with an emoji glyph, so the text disappears. Only all-digit forms such as `:05:` in `06:05:43Z` or `:100:` are not matched (residual R-8). A line that matches `_DELIMITER_ROW_RE` (the R5(b) delimiter row, which holds only `|`, `:`, `-` and spaces) is exempt from R4, so a centre-aligned `:---:` is accepted. Error: `disclosure line <k>: ":<name>:" may render as an emoji instead of text; reword it`.
   - **R5. Table shape (Kind D).** All Kind D lines in the section must form **one** contiguous block. A second block → `disclosure section has more than one table (line <k>)`. Within the block:
     - (a) every row ends with `|` (`disclosure line <k>: table row must start and end with "|"`);
     - (b) the second row is a GFM delimiter row matching `^\|( *:?-+:? *\|)+$`, with the same cell count as the header (`disclosure callers table has no delimiter row matching its header`, the existing message);
     - (c) every row has exactly the header's cell count, because GitHub drops excess cells and so hides their text (`disclosure line <k>: table row has <m> cells, header has <n>`);
     - (d) the line before the header row is Kind A or Kind B, and the line after the last row is Kind A or EOF (`disclosure line <k>: table must have a blank line or section heading before it and a blank line after it`). A table cannot be the section's last line before a terminating heading, because R7 requires that line to be blank;
     - (e) [ARCH-R2 AR2-4] the table lies below `## Callers / readers checked`, and above `## Items dep-mapper left untraced` if that heading is present (`disclosure line <k>: the table must be the copied callers table, under "## Callers / readers checked"`).

     Cells are split on every `|`. That is exact here, because `\` and backticks are banned, so there are no escaped pipes or code-span pipes.
   - **R6. What ends the section [ARCH-R2 AR2-3, corrected].** Any col-0 line matching `^#{1,6}( |$)` that is not a copied heading ends the section (item 2). That includes `# x`, `### x`, `###### x` and a bare `##`. It does not fail through R3. The outcome is still fail-closed: the required tokens, the table, the untraced items and `Result: PASS` that follow fall outside the section, so items 2–4 fail. A heading with 1–3 leading spaces does not end the section. It is a Kind E line starting with `#` after the leading spaces are removed, so it fails R3. A `#` line without a following space or end of line (`#2162 ...`) does not end the section either, and fails R3.
   - **R7. Blank last line [ARCH-R2 AR2-2].** When a terminating heading follows the section (that is, the section does not run to EOF), the section's last line is Kind A. Error: `disclosure line <k>: the line before the heading that ends the disclosure section must be blank`. Without this rule, a table or paragraph at the boundary would rely on the heading interrupting it. The template ends with a blank line, so a faithful copy passes.
   - **R8. No GitHub closing references [AM-3].**
     - **Rule.** The section's lines, joined with `\n`, contain no match from `closing_keywords.find_closing_refs(text, repo_slug)`. The keyword pattern can span a newline, so the lines are checked as one joined text.
     - **Module.** `closing_keywords.py` is loaded by file path from `scripts/automation/closing_keywords.py` next to `suspension_manager.py`'s own directory (`Path(__file__).resolve().parent.parent / "automation" / "closing_keywords.py"`), with the same `importlib.util.spec_from_file_location` idiom as REQ-W-18. A load failure → `disclosure cannot be checked for closing references: closing_keywords.py could not be loaded`, and the check fails closed.
     - **Slug.** `repo_slug` is the constant `"_/_"`. Any match is an error, whatever its normalised key.
     - **Error.** One error per match: `disclosure line <k>: "<snippet>" is a GitHub closing reference to <key>; merging the PR would close it. Reword it (for example "issue N")`.
     - **Why.** A closing reference in the disclosure is never legitimate. Either it is the until-closed issue, and declaring it would end the suspension on merge, or it is trace text that submit_pr.sh would refuse. The rest of the body is left to submit_pr.sh's own guard and the step's `--closes` declarations. The AI-Submitted block's `Closes #N` lines are legitimate there, for example in step2204 and step2263.
     - **Order.** R8 is checked after R1–R7. Its errors are collected like the others.

   **Required values and forbidden characters.** None of the required values needs a character outside R1:
   - `Data confidence: LOW` (now written without backticks);
   - `contract/gate-suspension.md`;
   - `dep_trace_path(step)`, which is `.claudetmp/oversight/step{N}-dep-mapper-trace.md`. It has no `_`, and a step id such as `2171s4` is alphanumeric;
   - `Result: PASS`;
   - `expires: YYYY-MM-DD` or `none`;
   - [AM-3] `until-closed: issue N` or `none`, never `#N` (see item 5 and R8). The template line starts with `(`;
   - this repo's `Authorized by:` value, `ScottThurlow (CODEOWNER approval of the PR that adds this file)`.

   `_` is allowed because changed-file paths need it (V5 coverage, for example `suspension_manager.py`). `*` is not allowed: no required value needs it, and it brings list markers, thematic breaks and emphasis with it. `.` and `:` are needed by the values above.

   Two cases where a value cannot be written:
   - **A consumer's `Authorized by:` value** fails R1, for example `<email>` or `&`. Item 5 reports `suspension "Authorized by:" value contains characters the disclosure section cannot carry; a human must change contract/gate-suspension.md`, and the check fails closed. An agent must not reword the value.
   - **A changed-file path** contains a forbidden character, for example `[`, `$` or `~`. V9 fails on the trace row, and the step stays blocked. Residual R-9: it fails closed and goes to the human.

   **What stays out of this item.** `_visible_markdown` is no longer called by `validate_disclosure`, and it may be deleted if nothing else uses it (today nothing does). Items 3–5 compare the raw section lines, split per R0. Cell normalisation (`_norm_cells`) is unchanged.

   **Residual statement (D-19, D-20).** Inside the section, any GitHub render extension, current or future, can act only on inline syntax built from the R1 characters, in line shapes R3 allows. Every known block-level construct (fences of any info string, math, HTML, blockquotes and alerts, footnotes, definitions, front matter, tables other than the one checked) is excluded by R1, R3 or R5. A future extension keyed on allowed characters is residual R-8. Outside the section, only block constructs that can carry across a col-0 ATX heading matter. P1–P3 ban the openers of the three that exist today (fences, math, HTML). The prefix is the fixed AI-Submitted template (D-20), so a future block extension there would have to come from that template.

`check_suspended_resolutions` passes the trace text it already validated (S5) and the default-branch suspension text. With either missing, the comparison fails closed. The check proves the disclosure repeats the trace; it cannot prove the trace is true (D-12).

### 5.4 `pr_readiness.py` REQ-W-18

`_check_dep_mapper_suspension(repo_root, manifest_path, step, base_sha, head_sha, risk_tier) -> CheckResult("REQ-W-18", ...)`, appended to the `checks` list after REQ-W-14. [AM-4] The signature becomes `_check_dep_mapper_suspension(repo_root, step, base_sha, head_sha, risk_tier)`.

- It loads `suspension_manager.py` by file path (`importlib.util.spec_from_file_location`), as the tests do. A load failure → FAIL, which fails closed.
- `risk-assessment.md` absent → PASS ("not applicable; REQ-W-04 owns absence"). This avoids reporting the same gap twice.
- `changed_files` comes from `git diff --name-only base..head`. A failure → FAIL.
- `human_gate_required` is read from the step manifest. A new helper mirrors `gate_compliance.gates_required`'s parsing, and an absent manifest or flag gives `False`. [AM-4] This is replaced. REQ-W-18 calls `eff = sm.effective_manifest_human_gate(step, head_sha, main, repo_root)` after `main = sm.read_default_branch_suspension(repo_root)`, and passes `human_gate_required=eff["flag"]` and `human_gate_error=eff["error"]` (§5.2.2). There is no caller floor here: the worker's own manifest reading is not an input. **The `manifest_path` parameter is removed** from `_check_dep_mapper_suspension`, and the `assess_pr_readiness` call site is updated. REQ-W-18 always uses the fixed `contract/step-manifest.yaml` relative to `repo_root`, at pinned SHAs. `assess_pr_readiness(step_manifest_path=…)` / `--manifest` still apply to the other checks (sign-offs, REQ gates), which are outside #2392. They do **not** reach REQ-W-18 (T-G10). This is the "fixed paths only" rule (D-6, §5.2 CLI). The tier is `risk_tier`, which [ARCH-R1] `check_suspended_resolutions` raises to the validated tier (D-17), because the worker supplies `--risk-tier` itself.
- [ARCH-R1] It reads `main_suspension_text` with `git show <default>:contract/gate-suspension.md` (a missing blob → `None`) and `worktree_suspension_text` from disk (D-16). [AM-2] It now gets `main_suspension_text` and `main_suspension_error` from `read_default_branch_suspension(repo_root)` (§5.2.1). It passes both, and never passes `ls_remote`.
- It calls `check_suspended_resolutions(..., handoff_text=<step handoff or None>, require_disclosure=True)`. [ARCH-R1] **It must not pass `today`, `issue_state` or `read_text`.** The production defaults (system UTC clock, live GitHub read) are the only path, and a test pins this (T-A4).
  - `applies=False` → PASS ("no suspended dep-mapper resolution").
  - `ok` → PASS ("dep-mapper LOW resolved by active suspension; trace and disclosure valid").
  - Otherwise → FAIL, with the joined errors.
- The `assess_pr_readiness` docstring changes to "REQ-W-01..W-14, W-18".

---

## 6. SPEC-82 authorship WARN (ESC-1, DEFERRED to a follow-up, not blocking)

**[ARCH-R1] Ruling: keep the SPEC-82 WARN unchanged in this build.** This was the worker's direction, and I confirm it. There is no architectural reason to decide the skip now. Keeping the WARN is the non-loosening option, and nothing in this design depends on the WARN being absent. The evaluator file gets **no** SPEC-82 edit (§9 row 7). The skip-when-identical idea below goes to a follow-up issue, which the worker files after merge, cross-referenced to #2167. It is recorded here only as input to that follow-up.

**Corrected consequence [ARCH-R1].** The worker's framing said "dependent steps … become CONDITIONAL_PROCEED". That is not what the evaluator does. SPEC-82 Step 2 checks `contract/gate-suspension.md` on **every** step whenever the file exists on disk, so **every** evaluated step in this repo becomes at least CONDITIONAL_PROCEED. Under `overseer.md`'s merge matrix (CONDITIONAL → HUMAN_REQUIRED), the overseer auto-merges nothing while the file exists. That is a repo-wide operational burden (the product-boundary checkpoint's "operational obligations"). It is disclosed at the top of this document, and the human clears it by approving the build PR. It is a tightening, so the safe default holds until the human says otherwise. The WARN item's cause is explained through the orchestrator's verification-recipe sub-line (§5.3), not by changing the WARN.

**Why the WARN also still matters [ARCH-R1].** Because the WARN now fires on every step, it no longer tells a tampered file from an untampered one. D-16 (S4 reads the default-branch blob) is the deterministic replacement for that signal on the one path that loosens.

**The problem (input for the follow-up).** Every squash merge on `main` is authored by the worker bot, so the last commit touching `contract/gate-suspension.md` will always be a bot's. Step 2 of `oversight-evaluator.md:576` then WARNs on every step for about 8 weeks, forcing CONDITIONAL_PROCEED on every step in the repo.

**Candidate for the follow-up (NOT in this build).** For `contract/gate-suspension.md` only, add a pre-step before the email check:
- If `git diff --quiet origin/main HEAD -- contract/gate-suspension.md` exits 0, **and** the working tree has no change to that file (`git diff --quiet -- contract/gate-suspension.md`), then the file is exactly what reached `main`, and it could only get there through the CODEOWNER-required PR review (`require_code_owner_reviews: true`; `/contract/` → `@ScottThurlow`).
- In that case, record: "authorship check: `contract/gate-suspension.md` unchanged from origin/main (CODEOWNER-gated path) — bot-email check not applied." There is no WARN.
- Otherwise, run the existing check unchanged. A branch that **modifies** the file still WARNs.

This is a git comparison, not a GitHub-approval verifier (#2167). A stale local `origin/main` from before the file existed makes the comparison fail, and the check falls through to the WARN, which is the safe direction.

**Why it needs a human (in the follow-up).** This removes a tamper-evidence WARN in one case, which is a loosening. It replaces an author-email heuristic with a reliance on branch protection. That reliance is weaker if a bot ever merges a protected path, which has happened before (see the bot-merge ratification issues, for example #1401). The follow-up must also use the default branch from `origin/HEAD`, not a hard-coded `origin/main`, because the evaluator is a shipped CORE agent.

**This build:** no change. The WARN fires on every step, and each one is CONDITIONAL_PROCEED with a conditional item until the file is removed.

**[AM-2; ARCH-R4 AR4-2] Binding constraint on the ESC-1 follow-up.** The SPEC-82 hold is currently the only bound on R-7's remaining window, which runs from the REQ-W-18 freshness check to the merge. So the follow-up must not let a step whose risk assessment has a `suspended:` resolution leave HUMAN_REQUIRED, unless the overseer re-runs `suspension_manager.py --check-suspended-resolutions` for that step's range immediately before auto-merging it, and routes any non-zero exit to HUMAN_REQUIRED. A follow-up that drops the WARN without that re-check would reopen R-7 at merge time. The worker must copy this constraint into the follow-up issue. Note that the re-check needs the step's `risk-assessment.md` and trace, which today exist only in the worker's `.claudetmp` (R-1). So the follow-up must also give the overseer access to them, or else keep the hold.

---

## 7. Exact content of `contract/gate-suspension.md` (new; written by the worker session)

```markdown
# Gate Suspension — dep-mapper LOW (time-boxed, #2214)

<!--
  PROVENANCE: drafted by the worker under the explicit human ruling quoted in
  Reason below, per the #2170 human-interface rule. The authorization is the
  CODEOWNER (ScottThurlow) approval of the PR that adds this file; the human
  wrote no file. Agents must not otherwise create or modify this file. To end
  the suspension early, a human removes the SUSPENDED line (or deletes the file)
  via an approved PR. It also stops suppressing on its own: from 2027-01-01 UTC,
  or as soon as #2162 is closed as completed (scripts/oversight/suspension_manager.py
  --suspension-status dep-mapper).
-->

Authorized by: ScottThurlow (CODEOWNER approval of the PR that adds this file)
Date: 2026-10-30
Approving PR: the merged PR that adds this file (Part of #2214); its number is the "(#<n>)" suffix of the adding commit — git log --diff-filter=A -- contract/gate-suspension.md
Reason: Human ruling on #2174, 2026-10-30, Q1 B: "suspend the dep-mapper LOW finding as blocking until #2162 lands or 2026-12-31, whichever is first; each affected PR keeps dep-mapper's manual trace and discloses LOW in its body; the suspension lands via a PR I approve." Implemented by #2214. Conditions enforced: dep-mapper still runs; a valid manual trace at .claudetmp/oversight/step{N}-dep-mapper-trace.md; the PR body carries the "dep-mapper LOW disclosure (suspended blocker)" section; never applies on CRITICAL or human_gate_required steps.
reason_category: OTHER

---

## Currently suspended

SUSPENDED: dep-mapper expires: 2026-12-31 until-closed: #2162

---

## Re-enable log

| Gate / Reviewer | Re-enabled | Notes | Authorized by |
|---|---|---|---|
| *(none yet)* | | | |
```

`Authorized by:` is the first line that `check_suspension.sh::print_suspended` greps. `reason_category` is in the SPEC-378 enum. No `security-suspension-acknowledged` line is needed.

---

## 8. Disclosed residuals

- **R-1. Time passes after `pr_readiness`.** A PR opened on 2026-12-31, or opened just before #2162 closes, can merge after the suspension expires. The overseer's 7b re-check is prose and cannot read the worker's `.claudetmp`. The bound is a gap of one merge cycle, and the PR body shows the disclosure.
- **R-2. Omitted findings are not caught.** risk-assessor could fail to record the LOW finding at all. Like every self-reported value under #204, it is not re-derived here, because no dep-mapper report path is standard.
- **R-3. Trace truth is unchecked** (D-12). Only structure, coverage and the PASS claim are checked.
- **R-4. Token expiry gives `unknown`.** An expired `GH_TOKEN` during the `until-closed` lookup fails closed, so the step blocks until the token is re-minted. This is the correct direction, but it adds friction.
- **R-5. Deliberate local tampering is out of scope [ARCH-R1].** There is no CLI flag for the clock, the issue state or the paths (D-6), and no injected argument at the production call sites (T-A4). An agent that sets out to subvert the check could still `LD_PRELOAD` a fake clock, repoint `origin` (a fork without #2162 → `unknown`, which fails closed), or `git update-ref` the local default-branch ref to a commit it made. Each of these is deliberate, leaves traces, and is beyond what a structural check can stop. The backstop is that the PR still goes to the human (§6) with the diff visible.
  - **[ARCH-AM4 AR-AM4-3] Step identity is caller-supplied, not bound.** AM-4 guarantees that a branch cannot lower the gate *for a given step id*. It does not bind the id to the work: `STEP` comes from the evaluator (an LLM) or the worker, and the risk assessment, trace and handoff that carry it are agent-written. A run under the id of an existing non-gated step needs no manifest change at all, under either polarity of D-22. A run under a new id needs a head manifest entry, which is a `contract/**` change and so CODEOWNER-reviewed at merge. This residual predates AM-4 and AM-4 does not widen it. Binding the step id (for example to the branch's issue number) is a follow-up, not part of this step. The PR's human summary must disclose it.
  - **[AM-4] Narrowed (#2392).** Tampering with the step manifest is no longer in this residual. An uncommitted edit or deletion fails G4. A committed loosening on the branch is overridden by the default-branch flag (G5), and on the default branch `contract/**` is CODEOWNER-gated. What remains for the manifest is a loosening that a human approves and merges to the default branch, which is a human decision and not tampering. Also outside AM-4: `pr_readiness --manifest` can still point the *other* REQ checks (sign-offs, gates) at an arbitrary file. That is a separate gap, which AM-4 neither fixes nor widens.
  - **[AM-4 AL-WD] Working-tree path race.** G4 now `lstat`s every intermediate component (AL-WD-10). A swap of `contract/` between that `lstat` and the read is a deliberate local race, and stays in this residual. The bytes must still equal the head blob, and the flag comes only from the pinned blobs.
- **R-6. The PR body is not mechanically bound to `handoff.md` [ARCH-R1].** REQ-W-18 checks `step{N}-handoff.md`. `submit_pr.sh --body-file` accepts any path. By convention the orchestrator passes the handoff. The human sees the real body on every such PR (§6). Binding `submit_pr.sh` to the handoff is not in scope.
- **R-7. A stale local default-branch ref [ARCH-R1]. NARROWED by AM-2 (§5.2.1) [ARCH-R4 AR4-2].** When the evaluator or REQ-W-18 runs, S4 now takes the default branch and its SHA from `git ls-remote --symref origin HEAD`. It requires the local ref to match, and reads the blob at that SHA. A stale or repointed local ref fails closed (E-F1 to E-F4).
  - **Remaining window.** Freshness is checked at evaluator/REQ-W-18 time, **not at merge**. A revocation after REQ-W-18 passes and before the PR merges is not caught by this check.
  - **Current bound.** While `contract/gate-suspension.md` exists, every evaluated step is CONDITIONAL_PROCEED because of the unchanged SPEC-82 WARN (§6), and so HUMAN_REQUIRED under the overseer's merge matrix. A human merges every such PR and sees the disclosure.
  - **That bound is temporary.** It disappears when the ESC-1 follow-up lands, which is why §6 and D-9 now constrain that follow-up.
  - The original text follows, for the record. S4 compares against the local `refs/remotes/origin/<default>`. If a human removes the line on `main` and the local ref has not been fetched, S4 still sees the old blob. `submit_pr.sh` fetches before pushing. pr_readiness runs earlier, so the gap is bounded by one fetch, and the working-tree comparison (D-16) catches a branch that has merged the newer `main`.
- **R-8 [AM-1]. Inline rendering of allowed characters.** The allowlist bounds what GitHub can do inside the section to inline syntax made of R1 characters. Each known case is still visible text, and none hides a whole line:
  - `_word_` and intraword `__x__` render as emphasis. For example, `scripts/__init__.py` shows as "scripts/**init**.py" with the underscores gone.
  - `#N`, `@name`, bare URLs and 40-character SHAs autolink. SHAs show shortened, and `@name` notifies that user. [ARCH-R2 AR2-9] Because the trace sections are agent-written and copied into the PR body, an `@name` in a trace notifies that user when the PR opens. dep-mapper should not write `@` mentions in the two copied sections.
  - All-digit emoji shortcodes such as `:100:` are not caught by R4 and render as a glyph.
  - A future GitHub inline extension keyed on allowed characters would also land here.

  The bound is that any such extension can change at most the inline rendering of allowed characters. It cannot hide a block.
- **R-9 [AM-1]. Content the grammar cannot carry fails closed.** A changed-file path, or a consumer's `Authorized by:` value, that needs a forbidden character blocks the step (V9 / item 5), and the step goes to the human. In this repo no current path or value is affected.
- **R-10 [AM-2]. Reliability: S4 now depends on the network.** A `--check-suspended-resolutions` or REQ-W-18 run makes one `git ls-remote origin` call, only when a suspension applies (`suspension_applies`); a step with no suspension makes no network call. The call is bounded at 60 s, with no prompt (`GIT_TERMINAL_PROMPT=0`).
  - If the network is down, the token has expired, origin is unreachable or the call times out, a `suspended:` resolution fails closed (E-F2). This is the same direction and friction as R-4, the `until-closed` issue read.
  - A step whose local ref lags origin, which is normal in a long cron cycle while other PRs merge, fails E-F1 until it runs `git fetch origin`.
  - No path fails open, and no retry is added. A re-run after a fetch, or after re-minting the token, is the recovery.
  - Steps with no `suspended:` resolution are unaffected by the outcome.
  - `--is-suspended` and the gate path make no new network call.
  - The bound is one ls-remote per invocation. reliability-reviewer and ops-reviewer must review E-F1 to E-F4 as new operator-visible messages.
  - [ARCH-R4 AR4-6] `GIT_TERMINAL_PROMPT=0` suppresses only git's own terminal credential prompt. It does not stop an ssh passphrase or host-key prompt, or a configured askpass helper. Those are bounded by `_git`'s 60 s timeout, which then gives E-F2. `BatchMode` is deliberately not forced, so the operator's ssh configuration is respected.
  - The PR must disclose R-10 and the remaining R-7 window (ARCH-R4).

---

## 9. Build file list (12 files, counting this TD)

| # | File | Author | Change |
|---|---|---|---|
| 1 | `scripts/oversight/suspension_manager.py` | coder | §3, §4.3–4.4, §5.1–5.3. Module docstring: add the new flags and CLI modes. The ratchet sentence stays: no code path writes a SUSPENDED line. [AM-1] V9, and §5.3 items 1, 2 and 6 (R0, P0–P5, P7–P9, R1–R7). Remove the `_visible_markdown` call from `validate_disclosure`. [AM-2] §5.2.1: `read_default_branch_suspension`, `_default_ls_remote`, the `_git` `env` overlay, the required `main_suspension_error` argument and the S4 error substitution. [AM-4] §5.2.2: `_manifest_gate_scan`, `read_manifest_gate_at` and `effective_manifest_human_gate`; `manifest_human_gate_required` becomes a wrapper with unchanged behaviour; the required `human_gate_error` argument and the S3 substitution; and the CLI wiring inside the `suspension_applies` branch. [AM-4 AL-WD] `_manifest_scan`'s whole-document allowlist, U+FEFF in the pre-scan, the optional outside-line helper, the intermediate-component `lstat` in G4, and the docstrings (§5.2.2 AL-WD). |
| 2 | `scripts/automation/lib/pr_readiness.py` | coder | REQ-W-18 (§5.4). [AM-2] Use `read_default_branch_suspension` and pass `main_suspension_error` (§5.2.1). [AM-4] Drop `manifest_path` from `_check_dep_mapper_suspension`, call `effective_manifest_human_gate` and pass `human_gate_error` (§5.4). |
| 3 | `tests/oversight/test_suspension_timebox.py` (new) | unit-test / coder | §10. Covers both modules. Existing `test_suspension_manager.py` and `test_pr_readiness.py` must still pass unchanged. [AM-4] Group (i). [AM-4 AL-WD] T-G27 to T-G34, the T-G21 block-end amendment, and the `_oracle_step_ids` / `_assert_never_looser` helpers. |
| 4 | `contract/gate-suspension.md` (new) | top-level worker session | §7, verbatim |
| 5 | `contract/OVERSIGHT-CONTRACT.md` | worker session | §7, after 7b: one sub-item 7b(iii) stating §5's rule, D-7 and D-8. Also one sentence: only status `active` counts as suspended (D-4), with the D-2 date semantics. |
| 6 | `.claude/agents/risk-assessor.md` | worker session | Replace Phase-3 item 2's two bullets with §1 step 2. Add the resolution form as an example under the `blocking_findings` schema. |
| 7 | `.claude/agents/oversight-evaluator.md` | worker session | (a) Gate-suspension handling: a role counts as suspended only if `--suspension-status <role>` exits 0. (b) 7b(ii): a `suspended:` resolution is resolved only if `--check-suspended-resolutions N --range B..H --tier <validated> --human-gate-required <manifest>` exits 0. Any other exit → COMPLIANCE FAIL, listing the ERROR lines. (c) [ARCH-R1] **No SPEC-82 change** (ESC-1 deferred, §6). (d) Line 706 is unchanged. (e) [ARCH-R1] 7b(ii): a `source: dep-mapper` finding with `resolved: …` → COMPLIANCE FAIL (D-15). The CLI reports it too, but the prose rule must say so, because `--check-suspended-resolutions` is only consulted when a `suspended:` or dep-mapper finding exists. (f) [AM-4] No change: the CLI owns the pinned manifest read (§5.2.2). |
| 8 | `.claude/agents/dep-mapper.md` | worker session | "How risk-assessor treats LOW confidence": suspension no longer means "do not block" by itself. Add a "Manual-trace mode" subsection with the §4.2 template and the rule that the trace must be produced by a dep-mapper invocation, not by the step's coder. [AM-1] Add the §4.2 character rule for the two copied sections (V9). |
| 9 | `.claude/agents/oversight-orchestrator.md` | worker session | The §5.3 section rule for `step{N}-handoff.md`, on PROCEED and on CONDITIONAL_PROCEED, using the generic template. [ARCH-R1] Plus the SPEC-82 verification-recipe sub-line (§5.3). [AM-1] The D-20 placement (insert, do not append), the AM-1 template, and a short statement of the R1/R3 rules in place of the denylist text. [AM-3] Write until-closed as `issue N`, not `#N`, and never pass `--closes` for the until-closed issue. [ARCH-AM3, architect-applied] The rule covers the whole PR, not only the disclosure: no PR title, body line or commit message in the range may put a closing keyword in front of the active suspension's until-closed issue (for example `until-closed #2162` or `closes #2162`). GitHub would close the issue on merge, from the body or from the commit message that reaches the default branch, and that ends the suspension. When `submit_pr.sh` refuses on that issue, the fix is always to reword (amend or squash the commit message). The guard's "If it IS intended, pass --closes" advice never applies to the until-closed issue. |
| 10 | `scripts/framework/validation-stamps/phase1-<hash>.stamp` | worker session | Produced by `run_framework_validation.sh` after the agent edits. |
| 11 | `prompts/scripts/oversight/suspension_manager.v2214.md` | coder (capture_prompt) | One prompt artifact. [ARCH-R1] It is cited by the `Prompt-Artifact:` trailer on **every** commit in the range, including the TD, contract, agent and stamp commits, because REQ-W-10 checks every commit at MEDIUM+ (`pr_readiness.py::_check_prompt_artifact_trailers`), not only the code commits. |
| 12 | `docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md` | technical-design | This document |

**Not in the build:**
- `contract/gate-suspension.template.md` (D-10).
- `framework_consumer_files.txt`: the new file must stay repo-local.
- `SCRIPTS-INDEX.md`: the first docstring lines are unchanged, so the index does not change. The build should confirm this with `regen_all.sh --check`.

The PR uses `--closes 2214`.

---

## 10. Tests mapped to acceptance

Tests use in-process calls, a fixed `today`, and a stub `issue_state` that records its calls. Tests never use the network.

**(a) Passes:**
- **T-A1.** The fixture suspension line, `today=2026-11-06`, issue `("open", None)`, a valid trace, and tier HIGH. `check_suspended_resolutions` returns `ok`, and `--check-suspended-resolutions` exits 0.
- **T-A2.** REQ-W-18 PASS on a tmp repo with risk-assessment, trace and a valid handoff disclosure. Uses a real git range.
- **T-A3.** A trace fixture derived from `step2171s4-dep-mapper-trace.md` with only the §4.5 edits validates.

**(b) Blocked without the conditions:**
- **T-B1.** Trace absent → not ok (S5). REQ-W-18 FAIL.
- **T-B2.** Each of V1–V8 violated separately → invalid, and the specific error is named. This includes an uncovered changed file, a `fail` row, a missing `Result: PASS`, and a stale `Range:`.
- **T-B3.** The disclosure is missing, or a required token is missing → REQ-W-18 FAIL. The evaluator-mode call (no `--require-disclosure`) still passes.
- **T-B4.** Tier CRITICAL, or `human_gate_required` true, with a valid trace → not ok (S3).
- **T-B5.** `source: risk-assessor` with a `suspended:` resolution → not ok (S1).
- **T-B6.** A non-convention trace path → not ok (S2).
- **T-B7.** `--check-suspended-resolutions` without `--tier` → exit 2.

**(c) Expiry and fail-closed behaviour:**
- **T-C1.** `today=2026-12-31` → `active`.
- **T-C2.** `today=2027-01-01` → `expired`, and the stub was **not called**.
- **T-C3.** Issue `("closed", "completed")` → `expired`.
- **T-C4.** Issue `("closed", "not_planned")` → `active`.
- **T-C5.** The stub raises, or returns `("closed", None)` → `unknown`.
- **T-C6.** An unknown flag, `expires: 2026-13-45`, a repeated `expires:`, or two `SUSPENDED: dep-mapper` lines → `malformed`.
- **T-C7.** `cmd_is_suspended("dep-mapper")` returns 1 for each of expired, unknown and malformed (monkeypatched `_today` and `_default_issue_state`). Also, with T-A1's inputs, the full CLI flow gives a `suspended:` resolution that is **not ok** once `today=2027-01-01`.
- **T-C8.** Backward compatibility. `SUSPENDED: lint`, `SUSPENDED: types [pinned]` and `SUSPENDED: lint review-by: 2020-01-01` are `active` and make no stub calls. `parse_suspensions` returns the same objects as before for these lines.
- **T-C9.** Census never calls the stub, and it flags an expired date.
- **T-C10.** `cmd_auto_remove` never removes the dep-mapper line, even with 99 recorded passes.
- **T-C11.** `--today` is rejected by argparse. `--suspension-status` ignores `--suspension-file`.
- **T-C12.** The shipped `contract/gate-suspension.md` parses to gate `dep-mapper`, `expires 2026-12-31`, `until_closed 2162`, `reason_category OTHER`. With the open stub and `today=2026-11-06` → `active`.
- **T-C13 [ARCH-R1].** Stub `("open", None, ["completed"])` (closed as completed, then reopened) → `expired`. `("open", None, [None])` → `expired`. `("open", None, ["not_planned"])` → `active`. The stub raising `ListTruncatedError` → `unknown`.

**(e) Anti-gaming [ARCH-R1]:**
- **T-B8.** `main_suspension_text=None` (the file is not on the default branch) with a valid working-tree file → not ok (S4). A working tree that differs from the main text (for example `expires: 2027-12-31`) → not ok (S4). A tmp-repo CLI run without a `refs/remotes/origin/main` blob → exit 4.
- **T-B9.** `source: dep-mapper` with `resolution: resolved: suspended per gate-suspension.md` → not ok (S7), and `applies=True`.
- **T-B10.** A `risk-assessment.md` whose `resolution: suspended:` line the block parser cannot reach (for example, the entry is placed after a column-0 comment) → not ok (S0 count mismatch).
- **T-B11.** `--tier HIGH`, with `validated_tier: CRITICAL` in the header → not ok (S3). `validated_tier` absent → not ok (S3). `--human-gate-required false`, with the manifest flag true → not ok (S3).
- **T-B12.** The header `base_sha`/`head_sha` differ from `--range` → not ok (S0).
- **T-A4.** REQ-W-18 with `suspension_manager._today` and `_default_issue_state` monkeypatched to sentinels. Both sentinels are called, which proves `pr_readiness` passes no `today` or `issue_state` override.

**(d) The parked steps** are documented in §11. There is no test.

**(g) Default-branch freshness [AM-2].**

Tests use tmp git repos. Origin is a local bare repo, and `ls_remote` is a stub. No test uses the network.

All T-F tests use the AR4-1 form. The production `_default_ls_remote` runs a real `git ls-remote --symref --exit-code origin HEAD` against the bare origin, whose `HEAD` points at `refs/heads/main`. Stub cases return `(D, sha, None)` or `(None, None, reason)`.

- **T-F1 (match passes).** Local `origin/main` equals the bare origin's `HEAD`→`main`. The reader returns the blob text, `error=None`, `branch="main"`, and `sha` equal to that SHA. The end-to-end `--check-suspended-resolutions` exits 0 with T-A1's inputs. Variant: the bare origin's `HEAD` points at `trunk`, and local `origin/trunk` matches → passes with `branch="trunk"`, and no `main` is consulted.
- **T-F2 (mismatch).** The bare origin gets a new commit on its default branch, and the clone does not fetch → `text=None`, and E-F1 shows both 12-character SHAs. The CLI exits 4, prints `ERROR=<id>: S4: local origin/main is …`, and does not print `suspension not on the default branch`. Also: local `origin/main` ahead of origin → E-F1.
- **T-F3 (ls-remote failure).**
  - The stub returns `(None, None, "exit 128: fatal: could not read Username")` → E-F2 with that reason.
  - A real run with `origin` pointing at a nonexistent path → E-F2, with a reason starting `exit `.
  - Exit 2 → `origin reports no HEAD`.
  - [AR4-1] stdout with a SHA line but **no** `ref: … HEAD` line, as a dumb or old server can send → E-F2 with `did not report its default branch`. It must not fall back to `main`.
  - Two symref lines, or no SHA line, or a short SHA → `ambiguous or incomplete`.
  - A symref of `refs/heads/-x` or `refs/heads/a..b` → `unusable default-branch name`.
- **T-F4 (timeout).** Monkeypatch `subprocess.run` so that the ls-remote call raises `TimeoutExpired` → E-F2 with `did not complete within 60s`. Assert that the call's argv is `ls-remote --symref --exit-code origin HEAD`, that it used `timeout=60`, and that its `env` had `GIT_TERMINAL_PROMPT=0`.
- **T-F5 (revoked suspension, stale local ref).** The CWE-362 reproduction, in the AR4-1 form. The clone and its worktree both hold the active `SUSPENDED: dep-mapper` file at the old default-branch commit. A second commit on the bare origin's default branch removes the `SUSPENDED:` line, and the clone does not fetch → not ok (E-F1), REQ-W-18 FAILs, and the CLI exits 4. After `git fetch origin`, S4 fails with the D-16 worktree-mismatch or `absent` error, not E-F1. Before AM-2, this scenario passed.
- **T-F6 (local ref missing).** The bare origin reports `main`, and the clone has no `refs/remotes/origin/main` → E-F3, naming `origin/main`.
- **T-F7 (read at the verified SHA).** The remote reports SHA X, equal to local. Between the reader's comparison and its `ls-tree`/`show`, a `_git` wrapper moves `refs/remotes/origin/main` to Y. The returned text is X's blob.
- **T-F8 (required argument).** Calling `check_suspended_resolutions` without `main_suspension_error` raises `TypeError`.
- **T-F9 (callers unchanged).** `cmd_is_suspended("dep-mapper")`, `--suspension-status dep-mapper` and `check_suspension.sh` with an `ls_remote`/`subprocess` spy make no ls-remote call.
- **T-F10 [ARCH-R4 AR4-1] (repointed local origin/HEAD).** The agent pushes branch `evil`, carrying an added `SUSPENDED: dep-mapper` line, to the bare origin, fetches it, and runs `git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/evil`. The worktree equals `evil`'s file. The bare origin's `HEAD` still points at `main`, which has no suspension → not ok. The reader uses `branch="main"`, and S4 fails with `not on the default branch` (main has no file) or the D-16 mismatch. The test asserts that the local `origin/HEAD` was never read: a `_git` spy sees no `symbolic-ref` call.
- **T-F11 [AR4-4] (decoy refs).** The bare origin also carries the branches `x/HEAD` and `x/refs/heads/main`. `ls-remote --symref origin HEAD` then returns extra lines (`<sha>\trefs/heads/x/HEAD`). The reader ignores them, because their second field is not exactly `HEAD`, and passes as in T-F1. A stub emitting two exact `HEAD` SHA lines → E-F2 `ambiguous`.
- **T-F12 [AR4-5] (missing blob vs read error).**
  - The verified commit has no `contract/gate-suspension.md` → `text=None, error=None`, and S4 says `suspension not on the default branch`.
  - `_git` returns `None` for `ls-tree` or `show` (timeout) → E-F4 with `timeout`.
  - `show` exits 128 → E-F4 with `exit 128: …`.
  - The path is a symlink (mode `120000`) → E-F4 with `not a regular file`.
  - S4 is not ok in every case.
- **T-A4 (extended).** REQ-W-18 with `_default_ls_remote` monkeypatched to a sentinel as well. The sentinel is called, which proves `pr_readiness` passes no `ls_remote` override.


**(f) Disclosure allowlist [AM-1].** Fixtures change first. `make_handoff` must produce the AM-1 template:
- no backticks;
- the AI-Submitted block as the prefix, with line 1 `## 🤖 AI-Submitted Pull Request` and a blank line before the disclosure heading (P7, P9) [ARCH-R2]. Every existing fixture without that first line now fails P7;
- a blank line after `Result: PASS` (R7);
- a blank line and the `## Callers / readers checked` heading before the table, and a blank line after it;
- the section followed by `# Handoff — Step {N}` and a suffix.

`make_trace` must satisfy V9. Every error assertion matches the rule's message prefix exactly, line number included.

- **T-D1 (D-21 invariant).** Fill the template from a V1–V9-valid trace and the shipped `contract/gate-suspension.md`, then insert it per D-20 into each of these:
  - a copy of `step2214-handoff.md`, which has the SPEC-82 recipe line with `<n>`/`<default>` after the section;
  - a suffix with backticks, `$VAR`, a fenced block, `<details>`, an HTML comment and `]:`;
  - a suffix ending with the attribution line.

  Each → valid. Also run the faithful case with a rewritten copy of each of the three real traces (§4.5) → valid. In every T-D1 body, line 1 is `## 🤖 AI-Submitted Pull Request` and a blank line precedes the disclosure heading (P7, P9).
- **T-D2 (P1).** Each of the following before the heading → the P1 error. A prefix line that only mentions backticks mid-line (`see three backticks here`) → valid.
  - three backticks, `~~~`, three backticks + `math` and three backticks + `mermaid`;
  - each of `- `, `* `, `+ `, `1. `, `1) `, `> `, `> > `, `> - `, `  - `, `   > `, `    ` and `\t` + three backticks + `geojson`;
  - `~~~topojson` inside a list item, and three backticks + `stl` inside a blockquote.
- **T-D3 (P2).** Before the heading, each of these → the P2 error:
  - `$$` on its own line;
  - `$$\color{white}` … `$$` wrapping text;
  - `x $\color{white}y$`;
  - `` $`a`$ ``.
- **T-D4 (P3–P5).** Each of these before the heading → its P error:
  - `<details>`, `<!--`, `<?x` and `<div hidden>`;
  - a `[x]: /u "` definition under each container prefix;
  - `[a](/u "t")`, `![i](/u)` and `[a][b]`.

  A plain `[text](https://x)` before the heading → valid.
- **T-D5 (P0).** U+0085, U+2028 and U+001C before the heading → the P0 error. A U+2028 placed so that `splitlines()` would see the heading at column 0 but `\n`-splitting does not → `heading missing`. This pins R0.
- **T-D6 (items 1–2, R6).**
  - Two disclosure headings → `appears 2 times`. Also when the second one is in the suffix, after `# Handoff` (AR2-7: the count covers the whole body).
  - The heading indented 1 space, or 4 spaces → `heading missing`.
  - The heading inside a blockquote (`> ## …`) → `heading missing`.
  - A section followed by a blank line and `# Handoff` → the section ends there, and a forbidden line after it is not reported.
  - [AR2-3] A col-0 `### x` placed before the copied table → the section ends at `### x`. Assert that items 2–4 report the missing `| Changed file` line, the missing table rows, the missing copied Items heading and the missing `Result: PASS`. Assert also that no R3 error is reported for `### x`. Repeat with `# x` and a bare `##`.
  - [AR2-3] ` ### x` (1 leading space) and `#2162 is open` at column 0 inside the section → R3, and the section does not end there.
- **T-D7 (R1).** Each of the following inside the section (as a prose line, as a bullet and inside a table cell) → the R1 error naming that character and its code point:
  - `` ` ``, `$`, `\`, `&`, `[`, `]`, `<`, `>`, `*`, `~`, tab;
  - U+200B, U+202E, U+00A0 and a Cyrillic `а`;
  - `|` in a prose line.

  `#2162`, `@name`, `{N}`, `—` and `→` in a prose line → valid.
- **T-D8 (R2, R3).**
  - 4-space and 6-space indented prose → R2. 2-space continuation lines and `  - ` nested bullets → valid.
  - Lines starting ` #` (1 space), `+ `, `---`, `___`, `===` or `:x` → R3. Lines starting `>`, `* ` or `***` → R1, because R1 fires first and `>` and `*` are outside the character set. `- [ ] task` fails R1 first too; assert that R1 is reported. (A col-0 `#`/`###` heading ends the section and is covered by T-D6.)
  - [AR2-6] `-` alone, `- ` with only trailing spaces (which becomes `-`), `-     x`, `-  x` (two spaces) and `- - x` → R3.
  - Lines starting `(`, `.`, `/`, `"`, `1. `, `- x` or `- none` → valid.
- **T-D9 (R4).** `:white_check_mark:`, `:x:`, `:X:`, `:White_Check_Mark:`, `:+1:` and `:-1:` → R4. `06:05:43Z`, `file.py:12:34`, `:100:` (residual R-8), `https://x` and `Result: PASS` → no R4 error.
- **T-D10 (R5).**
  - A table with no delimiter row → the existing message.
  - A pipe-less, escaped-pipe or wrong-count delimiter row → that message.
  - A data row with one extra cell, or one missing cell → the `cells` error.
  - A row without a closing `|` → the `start and end` error.
  - Two table blocks → `more than one table`.
  - A table directly after a prose line, or a prose line directly after the last row → the `blank line` error.
  - A table directly after `## Callers / readers checked` (no blank line) → valid (Kind B counts as the line before).
  - [AR2-4] A valid table placed under `## Items dep-mapper left untraced`, or above `## Callers / readers checked` → the `copied callers table` error (R5e).
- **T-D11 (fifth-bypass regression).** Reproduce the round-4 security body (`$$\color{white}` wrapping the copied table and untraced lines, with a delimiter row present). It must fail both when the wrapper is inside the section (R1) and when it is before the heading (P2). Do the same for a `- ` + three backticks + `mermaid` fence wrapping the table, inside the section (R1, because R1 fires first on the backtick) and before it (P1).
- **T-D12 (V9).** Each of the three real traces as they are today (§4.5) → V9 errors naming the section and line. The same traces rewritten per §4.2 → V9 passes. A trace table without a delimiter row → V9 (R5b).
- **T-D13 (item 5, R-9).** A suspension whose `Authorized by:` value contains `<` or `&` (R1), or `:smile:` (R4, AR2-8) → the fail-closed item-5 error, even though the disclosure copies it exactly.
- **T-D14 (suffix not checked).** Put `<!-- -->`, `]:`, `$$`, a fence and `[^1]: x` after the section's terminating `# Handoff` heading → valid. With `[^1]` inside the section → R1. This pins D-20.
- **T-D15 (P7–P9, ARCH-R2 AR2-1).**
  - Line 1 is `# Handoff — Step N`, a blank line, front matter `---`, or `## AI-Submitted Pull Request` without the emoji → the P7 error. `## 🤖 AI-Submitted Pull Request` followed by trailing spaces → valid.
  - A `### x` or `# Handoff — Step N` line in the prefix, after line 1 → the P8 error. This is the append-at-end placement.
  - The disclosure heading directly after a prefix paragraph line, a table row (`| a | b |`), a list item, or an open link-title line `[a](/u "` → the P9 error. The last case also fails P5.
  - The `oversight-orchestrator.md` template (lines 97–113) with the section inserted per D-20 → no P error.
- **T-D16 (R7, ARCH-R2 AR2-2).** `Result: PASS`, or the last table row, directly followed by `# Handoff` with no blank line → the R7 error (the table case also gets R5d). The section running to EOF with no trailing blank line → no R7 error.
- **T-D17 (V9, ARCH-R2 AR2-4/5/9).**
  - A trace with a valid table in `## Items dep-mapper left untraced` → the V9 `table rows are not allowed here` error. This pins D-21: no V9-valid trace can produce a disclosure that fails `more than one table`.
  - A trace whose callers table is directly under its heading (no blank line) → V9 passes.
  - A trace containing U+2028 or U+0085 before `## Callers / readers checked` → the V9 line numbers equal the `\n`-split line numbers, and V1–V8 use the same numbering.
  - Property-style: for each V1–V9-valid trace fixture in the file, the D-21 faithful disclosure → valid.

**(h) Closing-keyword safety [AM-3].**

- **T-K1 (new form passes).** The faithful disclosure with `until-closed: issue 2162` against the shipped suspension (`until-closed: #2162`) → valid. With a suspension that has no `until-closed:` and a disclosure saying `until-closed: none` → valid. `until-closed: issue 2162` against a suspension of `#2163` → the mismatch error, naming `issue 2163`.
- **T-K2 (old form fails clearly).** `until-closed: #2162` → not valid. The errors include the old-form message (`writes until-closed as "#N"`) and an R8 error naming key `2162`. `until-closed: GH-2162` → the same old-form message. `until-closed: issue 2162x` → absent.
- **T-K3 (regression against the real guard).** For each D-21 faithful disclosure the tests generate (T-D1's bodies, built from the shipped `contract/gate-suspension.md`), load `scripts/automation/closing_keywords.py` by file path and call `find_closing_refs(<disclosure section text>, "thurlow-research/HumanOversightSystem")`. Assert `[]`. Also run the CLI end to end, `closing_keywords.py check --repo-slug thurlow-research/HumanOversightSystem --body-file <generated full handoff>` with no `--closes`, on a body whose AI-Submitted and suffix parts have no closing reference, and assert exit 0. This pins the PR-gate interaction, so the template cannot regress.
- **T-K4 (R8).** In a section line or an untraced trace item, each of `fixes #12`, `Resolved: #12`, `closes GH-12`, `fix o/r#12`, `closed https://github.com/o/r/issues/12`, and `fixes` at a line end with `#12` at the start of the next line → the R8 error with that key. The same text in a trace → V9 (R8). `fixed in commit 1a2b3c` and `the closed issue 2162` → no R8 error. With `closing_keywords.py` unloadable (monkeypatched path) → the fail-closed load error.

**(i) SHA-pinned human gate [AM-4] (#2392).** These use the `repo` fixture (a local bare origin, no network). A variant fixture commits `contract/step-manifest.yaml` in the base commit, which is the pushed `origin/main`, and/or in the head commit, then regenerates the risk assessment and trace for the new head. Every message assertion matches the E-G prefix exactly.
- **T-G1 (uncommitted edit).** The manifest is committed with `human_gate_required: true` at base and head. The working tree flips it to `false` → REQ-W-18 FAIL with E-G2 `(modified)`. The CLI with `--human-gate-required false` → exit 4 with the same `ERROR=`. Variant: the manifest is committed `false` everywhere and the working tree changes it to `true` → still E-G2 (the comparison is byte-level and does not consider direction).
- **T-G2 (uncommitted deletion).** The manifest is committed `true` at head, and the working-tree file is deleted → E-G2 `(deleted)`, for REQ-W-18 and the CLI. Variant: no manifest at either SHA, and an untracked working-tree manifest saying `false` → E-G2 `(added but not committed)`.
- **T-G3 (committed loosening).** Base, which is `origin/main`, has `true`. The head commit sets `false`, and the working tree equals head → REQ-W-18 FAIL with the generic `S3: step is behind the human gate`. The CLI with `--human-gate-required false` → exit 4. This is the CWE-807 reproduction.
- **T-G4 (committed tightening allowed).** Base has `false`, or no manifest. Head sets `true` → S3 fails, so the tightening takes effect. Control: `false` at both, or absent at both → REQ-W-18 PASS and CLI exit 0.
- **T-G5 (default-branch read failure).** `effective_manifest_human_gate` with `default_read={"error": "S4: …", "sha": None, …}` → `{"flag": True, "error": E-G1}`. Also with `error=None` and `sha=None`. End to end, with `_default_ls_remote` stubbed to `(None, None, "x")`: the CLI prints both the E-F2 S4 line and E-G1, and exits 4. No manifest `ls-tree` runs before G1 fails.
- **T-G6 (non-regular file, read errors).** `contract/step-manifest.yaml` as a symlink (mode `120000`) at head → E-G3 `at head … (not a regular file)`. The same at the default SHA → E-G3 `at origin/main …`. A working-tree symlink whose target has bytes identical to head → E-G2 `(not a regular file)`. A `_git` wrapper returning `None` for the manifest `ls-tree` or `show` → E-G3 `(timeout)`. A `show` exit 128 → E-G3 `(exit 128: …)`. A short head SHA → E-G4. A `default_read` SHA of `-x` → E-G1.
- **T-G7 (absent everywhere).** No manifest at base, head or in the working tree → `{"flag": False, "error": None}`. The T-A1/T-A2 fixtures (which have no manifest) still pass. Assert this explicitly, because it is this repo's real configuration.
- **T-G8 (D-22).** The default-branch manifest lists only `other-step`, and head lists this step with `false` → flag False. The head manifest does not list the step → True. A default-branch manifest with an anchor, a garbage flag or no `steps:` block → True. Undecodable bytes at either SHA → True, with no error.
- **T-G9 (required argument, substitution).** Calling `check_suspended_resolutions` without `human_gate_error` → `TypeError`. With `human_gate_error="S3: X"` and `human_gate_required=False` → the finding's errors contain `S3: X`, do not contain `step is behind the human gate`, and `ok=False`. `run_check` gains `human_gate_error=None`.
- **T-G10 (refactor and fixed path).** Every existing `test_manifest_*` test passes unchanged. For each of those fixture texts, `manifest_human_gate_required(path)` equals `_manifest_gate_scan(text)`, with `None` mapped to True. `assess_pr_readiness(step_manifest_path=<tmp file saying false>)`, on a repo whose committed manifest says `true` → REQ-W-18 still reports S3, which proves the override does not reach it.
- **T-G11 (no new network call).** A `subprocess.run` spy shows that with `suspension_applies` false, the CLI and REQ-W-18 make no `ls-remote` call and no manifest `ls-tree`/`show` call. When it applies, there is still exactly one `ls-remote`. G5 reads at `default_read["sha"]` (assert the argv), not at a ref name.
- **T-G12 (CLI floor kept).** No manifest anywhere, with `--human-gate-required true` → the generic S3 message, exit 4.
- **T-G13 [ARCH-AM4] (D-22 canonicality).** Default lists `s1` as `true` with a folded id (`id: >-` then `s1`), and head lists `s1` canonically with `false` → effective True (the AR-AM4-2 reproduction). Also True on the default read: an indented `  steps:` block listing `s1`; a tab-indented `s1` item; `id: "s\x31"`; `id: !!str s1`; a duplicate `id:` in one item whose second value is `s1`; `s1` mentioned only in a comment. No `steps:` block at all on the default read → True (AR-AM4-1). Control: the default lists only `other-step` and `s1` appears nowhere → False, as in T-G8. `_manifest_gate_scan` on a text with no `steps:` line → True, not `None`.
- **T-G14 [AM-4 SR-1] (duplicate key in one item).** The repro (`- id: s1` / `id: s9` / `human_gate_required: false`, then `- id: "s\x31"` / `human_gate_required: true`) → True. Also True: a duplicate `id:` alone, where both values are canonical and the item says `false`; and a duplicate `human_gate_required:` in a **non-target** item. End to end: the default branch has the repro, and head lists `s1` canonically with `false` → effective True, with REQ-W-18 S3 and CLI exit 4. Control: two separate items, both `id: s1`, one of them `true` → True (the any-true rule is unchanged).
- **T-G15 [AM-4 SR-2] (second or non-canonical top-level `steps`).** True for each of these: block 1 (`s1: false`, `other`), then `name: x`, then a second `steps:` with `s1: true` at item indent 4; the same with the second block's items at indent 0; a second block keyed `"steps":`, `'steps':`, `steps :` or `? steps`; and a `---` or `...` line after content. Control: a single leading `---` before a canonical `steps:` that lists `s1: false` → False.
- **T-G16 [AM-4 SR-3 a–d] (escaped, tagged or explicit keys).** True for each of these: `"human_gate_\x72equired": true` (the codex repro; also the `r` form); `"i\x64": s1` with `true`, next to a canonical `s1: false` item; `!!str id: s1` with `true`, next to a canonical `s1: false` item; `? human_gate_required` / `: true`; and a single-quoted key containing `''`. End to end on the default read, with head canonical `false` → effective True. Controls, which are the existing tests run unchanged: `"human_gate_required": true` → True and `'human_gate_required': false` → False.
- **T-G17 [AM-4 SR-3 e–f] (canonical ids with the target found).** True for each of these: the `(False, ['s1', 's\\x31'])` repro (a canonical `s1: false` plus `id: "s\x31"` with `true`); `id:` with `s1` on the next line, next to a canonical `s1: false`; `id: 007` next to a canonical `s1: false`; and a `steps:` item that has no `id`. True on the path function and on both pinned reads. Control: `id: 's1'` with `false` → False (`test_manifest_quoted_id_and_flag_comment`, unchanged).
- **T-G18 [AM-4 SR-4] (git toplevel).** `repo_root` is the subdirectory `sub/`. The manifest is committed `true` at head. The toplevel working-tree manifest is modified, and an untracked `sub/contract/step-manifest.yaml` equals the head blob → E-G2 `(modified)`. Before SR-4, this case passed G4. Run the same case through the CLI with `cwd=sub/`. Control: `repo_root=sub/` with a clean toplevel → no error, so the read uses the toplevel file and not `sub/`. A `_git` stub that returns `None` for `rev-parse` → E-G5 `(timeout)`. A `repo_root` outside any repo, or a bare repo → E-G5 `(exit 128: …)`. A stubbed relative or non-existent output → E-G5 `(not an absolute directory)`. A `subprocess.run` spy shows that `rev-parse` runs after G3's `ls-tree`/`show` and before `lstat`.
- **T-G19 [AM-4 SR] (never looser than a parser; regression).** Every existing `test_manifest_*` test and T-G1 to T-G13 pass unchanged. For every fixture text in T-G14 to T-G17, `manifest_human_gate_required(path)` equals `_manifest_gate_scan(text)` with `None` mapped to True. Differential oracle, skipped if PyYAML is not importable: for every `test_manifest_*` and T-G13 to T-G17 fixture that `yaml.safe_load` accepts, if the loaded `steps` list has any item with `id == "s1"` and a truthy `human_gate_required`, then the scan must return True.
  [SR round 2, AR-SR-3] **This replaces the oracle sentence above.** The test imports `yaml` unconditionally, as other tests already do (`PyYAML>=6.0` is in `scripts/oversight/requirements.txt`). There is no `importorskip` and no skip marker, so a missing PyYAML fails the suite rather than silently skipping. For every `test_manifest_*`, T-G13 to T-G17 and T-G20 fixture, and for each step under test, if `yaml.safe_load` accepts the text, the loaded `steps` is a list, and any item has `str(item.get("id")) == str(step)` with a truthy `human_gate_required`, then `_manifest_gate_scan(text, step)` must be True. The fixtures add step `7` cases: `id: 007` with `true` next to a canonical `- id: 7` / `human_gate_required: false`, and the same with `id: 0x7`. Each must scan True. PyYAML loads both as the int 7, so the oracle exercises them. Fixtures that PyYAML rejects (the adjacent-colon, duplicate-key and second-document forms) stay covered by the explicit asserts in T-G14 to T-G17 and T-G20.
- **T-G15b [SR round 2, AR-SR-2] (colon-independent `steps`, document markers).**
  - True: a second top-level key written `"steps":[…]`, `steps:[…]` or `"steps":` with items below it; a leading `--- !tag`; a leading `--- steps: []`; a leading `...`; and a `--- # c` that comes after content.
  - Control: a leading `--- # header comment`, or a bare leading `---`, before a canonical `steps:` that lists `s1: false` → False.
- **T-G16b [SR round 2, AR-SR-2] (quoted span at the start of the body).**
  - True: `"i\x64":s1` / `human_gate_required: true` next to a canonical `s1: false` item; `"human_gate_\x72equired":true` (an adjacent colon, the codex repro); an unclosed `"human_gate_required: true`; an unclosed `'id: s1`; and `'human''gate': x` in the target item.
  - Control: `"human_gate_required":true` with no escape keeps today's result (True), and `'human_gate_required': false` → False (unchanged).
- **T-G20 [SR round 2, AR-SR-1] (flag value spelling).** The target item `s1` has `human_gate_required: <v>`.
  - True for each `<v>`: `"false"`, `'false'`, `'no'`, `fAlSe`, `no`, `No`, `NO`, `off`, `n`, `null`, `~`, an empty value, `!!bool false`, `0x0`, `00` and `0.0`.
  - False for each `<v>`: `false`, `False`, `FALSE` and `0`, each also with a trailing `# comment`.
  - Check the path function and both pinned reads. End to end: the default branch lists `s1` with `"false"`, which a parser reads as a truthy string, and head lists `s1` with canonical `false` → effective True, REQ-W-18 S3 and CLI exit 4.
  - Every value is also run through the T-G19 oracle.

**[SR round 3, AM-4 SR-AL] Tests, to be done in one batch.** These fold in the round-SR test-unit and code-review findings from the register.
- **T-G21 (the AL-1/AL-2 grammar, direct unit tests).** Parametrised tests on `_classify_steps_line`, one case per form and per rejection, run in isolation so that no other rule masks a result.
  - **Accepted:** L-blank (`""`, `"  \t"`); L-comment (`"  # x — y"`); L-item with 1 and 3 spaces after `-`; L-key with each `VALUE` class; quoted keys `"id"` and `'id'`; `id` as plain, `'s1'` and `"7"`; flag values `false`, `False`, `FALSE`, `0`, `true`, `True`, `TRUE` and `1`; `PLAIN` with single internal spaces; `DQ` with non-ASCII; `SQ` with `''`; `FLOW` empty and populated; and a trailing `# c` after a tab.
  - **Rejected:** a tab in the indent; a tab after `-`; a bare `-`; an empty value; `key:value`; a key with an escape, `''`, a space or non-ASCII; `!`- and `?`-prefixed keys; plain `id` values `yes`, `null`, `On`, `007` and `s1 x`; `PLAIN` with two spaces or a `:`; an unclosed `DQ`, `SQ` or `FLOW`; `DQ` with `\`; `|`, `>`, `&a`, `*a`, `!!str x` and `{a: b}` as values; and `false#x`.
  - **Direct tests of the helpers that remain.**
    - `_bad_quoted_span`, if it is kept: a clean double-quoted span gives False (the missing control); an unclosed `"` and an unclosed `'` each give True, in isolation; a `\` at index 1 gives True; `''` gives True; a lone `'` close gives False.
    - `_is_steps_key_line`: `? steps` alone gives True, with no other gating path in the fixture; `steps:[a:b]` gives True, which kills the `rsplit` mutant; `"steps":`, `'steps' :` and `stepsx:` (False) are included.
  - **Mutation target.** At least 75% per function for `_classify_steps_line`, `_manifest_scan`, `_is_steps_key_line`, `_bad_quoted_span` (if kept) and `effective_manifest_human_gate`. Each surviving equivalent mutant is documented in the test-unit register entry (`Equivalents_documented: true`) and is not subtracted silently.
- **T-G22 (security finding 1: Unicode whitespace).**
  - True for each of U+00A0, U+3000, U+2003, U+202F, U+1680 and U+200A in each of these positions:
    - after `false`;
    - after `0`;
    - before the value;
    - between the value and ` # c`;
    - replacing the space before `#`;
    - in the indent;
    - after `-`;
    - between the key and `:`;
    - after `id: s1`, with the flag `false`;
    - as a line holding only that character.
  - Each is run on the path function and on both pinned reads.
  - End to end: the default branch has `false<NBSP>` and head has a canonical `false` → effective True, REQ-W-18 S3 and CLI exit 4.
  - Controls: non-ASCII in a comment, and `name: "a — b"`, each next to a canonical `false` → False.
- **T-G23 (security finding 2: continuation and nesting).** True for each of these:
  - `human_gate_required: false` followed by a deeper `true`, `5` or `b"`;
  - `id: 5` followed by a deeper `x`, with the flag `false`, against step `5`; and the same with `id: s1` / deeper `x` against step `s1`;
  - `risk_tier: LOW` followed by a deeper `HIGH`;
  - `required_signoffs:` followed by a nested `- code-review`, with the flag `false`;
  - a line at an indent between `item_indent` and `key_indent`;
  - an L-key before the first item.

  Control: `required_signoffs: [code-review]` with the flag `false` → False.
- **T-G24 (canonical manifests).**
  - `contract/step-manifest.template.yaml`, read from the repo: `_manifest_gate_scan` for steps `1`, `2` and `3` gives False, False and True.
  - The same template committed as the default and head manifest in the `repo` fixture: step `3` → effective True, and step `1` → False.
  - If `contract/step-manifest.yaml` exists, it is also run through the T-G19 oracle, for every id it lists. It is absent in this repo, and T-G7 already covers that case.
- **T-G18 (round 3 fix).**
  - Rename `test_g18_outside_any_repo_is_e_g5_exit_128` to describe what it actually asserts, which is the head-read error that fires first.
  - Add a **real** outside-repo E-G5 case. A `_git` wrapper passes `ls-tree` and `show` to the real fixture repo, but runs the real `git rev-parse --show-toplevel` with `-C` set to a fresh `tempfile.mkdtemp()` outside any repo. The test asserts the E-G5 text, with `exit 128:` and real stderr.
  - The bare-repo case stays.
- **T-G25 (AL-6).**
  - `subprocess.run` raising `FileNotFoundError` for `rev-parse` only → E-G5 `(timeout or git could not start)`.
  - A stub exiting 128 with empty stderr → E-G5 `(exit 128)`.
  - E-G3's and the suspension file's `timeout` messages are unchanged (T-F12 is not affected).
- **T-G19 (round 3: non-vacuous and complete).** This **supersedes** the hand-copied fixture subset (`_G19_EXISTING`).
  - Move every `test_manifest_*` body, the T-G13 fixtures and the G14–G17, G15B, G16B, G20, G22, G23 and G24 fixtures into module-level collections. The original tests and the oracle both consume them, so nothing is copied by hand.
  - For each fixture and each step under test, assert `manifest_human_gate_required(path) == _manifest_gate_scan(text)`, with `None` mapped to True.
  - Run the PyYAML oracle on every fixture. Skip non-dict items ([ARCH-AM4-SR round 2] note).
  - **Minimum firing counts.** Assert a floor for two counts: how many fixtures `safe_load` accepts, and how many times the oracle's "parser sees gated" branch fires. The floor is the count observed when the test is written, minus nothing. If a fixture refactor quietly empties the oracle, the test fails.
  - The step-`7` `007` and `0x7` cases stay in.

**[SR round 4] Tests.** The T-G21b, T-G25b and T-G24 fixtures are added to the T-G19 collections.
- **T-G21b (AR-AL-1: block end).** True for each of these:
  - the architect's repro, which is `steps:` / `  - id: s1` / `    human_gate_required: false` / `# c` / `  - id: s1` / `    human_gate_required: true`;
  - the same with a column-0 blank line (and a column-0 tab-only line) in place of `# c`;
  - a line starting with NBSP between items;
  - a line starting with a tab between items;
  - a line starting with U+3000 between items.

  Control: a column-0 `# c` and a column-0 blank line between two **different** canonical `false` items (`s1`, `other`) → False for `s1`. That shows the block continues past them and stays canonical. Direct test: a column-0 `x: 1` after the block ends it, and the scan result is unchanged.
- **T-G25b (AR-AL-2: outside-block quoted and tagged keys).** A canonical first block lists `s1: false`, then a second top-level block follows, keyed `"st\x65ps":` or `!!str steps:`, that lists `s1: true` → True for each. The same applies with `? steps` and with an unclosed `"steps` at top level. Control: a later top-level `"name": x` with no escape → no effect, so the result is False.
- **T-G24 (round 4 addition).** After the coder's AR-AL-3 edit, the template still scans steps `1`, `2` and `3` as False, False and True. A text assertion confirms that the comment line directly above `steps:` mentions both `[a, b]` and single-line values.

**[AM-4 AL-WD] Tests.** T-G27 to T-G34 are specified in §5.2.2 under "Tests (AL-WD)", with the amendment to `test_g21_block_ends_at_every_ascii_printable_first_char_except_dash_and_hash` (`~` and `}` now give `(True, [])`). Their fixtures join `_G19_TEXTS`, and the two T-G19 floors are raised to the newly observed counts. T-G24's real-manifest test takes its step ids from the PyYAML oracle (AL-WD-11).

**Existing tests that AM-4 changes.** `test_b11_cli_manifest_flag_cannot_be_lowered` and `test_req_w18_manifest_flag_and_tier_floor` write the manifest into the working tree without committing it. Under AM-4 they get E-G2, not the generic S3 message. Convert them to the committed form (T-G3/T-G4) and keep the uncommitted form as T-G1. Do not delete them. The `req_w18` helper and the direct `_check_dep_mapper_suspension` call in the tier-floor test drop the `manifest_path` argument.

**Existing tests that AM-1 inverts or retires.** In `tests/oversight/test_suspension_timebox.py`, the unit-test agent must convert each of these to its T-D equivalent, not delete it:
- `test_2349_html_comment_anywhere_in_body_fails`: the suffix case becomes valid (T-D14). The prefix and in-section cases keep failing under P3 and R1.
- `test_2349_fence_follows_commonmark_closing_rules`: the `longer` and `notfence` cases now fail P1, because no fence is allowed before the heading.
- `test_2349_escaped_angle_bracket_is_fine`: `&lt;` now fails R1.
- `test_2214_inline_link_is_not_flagged`, `test_2214_task_list_item_is_not_a_link_reference_definition` and `test_2214_plain_links_and_attribution_pass`: in-section links and task items now fail R1. The prefix and suffix forms stay valid.
- `test_2349_link_reference_definition_rejected_including_title_continuation`, case `h2`: a definition placed after the section is now not an error (T-D14).
- Every assertion that matches the old message substrings (`raw HTML`, `link-reference definition`, `link with a title`) must match the new P- or R-rule message instead.

---

## 11. Parked steps that can proceed after merge (acceptance d)

These are eligible only **after** the build PR merges, so the suspension is active on `main`. Each one must, at re-entry:
1. Merge `main`.
2. Re-run risk-assessor on the new full-SHA range.
3. Confirm the effective human gate does not fire.
4. Confirm dep-mapper LOW is the **only** unresolved blocking finding.
5. Write or refresh the §4 trace.
6. Pass evaluator 7b and REQ-W-18.

| Issue | Local head (per worker records) | Tier | Notes |
|---|---|---|---|
| #1789 | `1f5ced2e0` | HIGH | Only the dep-mapper LOW A/B/C was pending. |
| #2059 | `d99de0fee` | HIGH | pip-audit is resolved. Only dep-mapper LOW is left. |
| #2171 s4 | `b0fddb358` | HIGH | Existing trace; needs the §4.5 edits. |
| #1988 | `c27e9e083` | HIGH | Needs a new trace (the existing file is a report). |
| #2216 | `c51308f23` | HIGH | |
| #2166 | `7d8078fc2` | HIGH | |

**Not eligible.** These are parked on other blockers, not dep-mapper LOW: #2151+#2101 (C14), #2122 and #2230 (C10 FP), #2226 (W-08), #1605 P3 (16th-file waiver). #2174 itself merged as PR #2225.

**Finding any others.** Any other parked step qualifies if its escalation names dep-mapper LOW as its only blocker. Look for escalations naming dep-mapper LOW on open `needs-human` issues (`bootstrap/query_issues.sh --list --label needs-human` then `--comments <n>`).

### 11.1 This build step itself (ESC-2) [ARCH-R1]

#2214's own step is HIGH and changes Python and shell-adjacent files. #2162's premise ("every HIGH shell/Python diff escalates on Data confidence: LOW") means dep-mapper will very probably report LOW here too. **This step cannot resolve that through the suspension it adds.** Under D-16, the file is not on the default branch yet, so S4 fails. That is correct under the ratchet: a step that loosens a gate must not be the first to benefit from the loosening before a human has approved it.

If dep-mapper reports LOW on this step:
1. risk-assessor records `resolution: unresolved`. The evaluator then ESCALATEs, and the orchestrator does not open the PR.
2. The worker writes the §4 trace for this step anyway, plus the §5.3 disclosure in the handoff, so the human has the same evidence as on any later step.
3. The worker asks ESC-2 (top of this document) with `bootstrap/escalate_to_human.sh` and opens the PR only after an explicit "A". Under #2170 the human does not write a file, so the human's comment is the "explicit human instruction" that `oversight-orchestrator.md` requires to override ESCALATE. The PR body quotes that comment. The mechanism is the same as the existing one-time dep-mapper-LOW precedent: #2157 → PR #2163 (ruling B, 2026-10-25, LOW disclosed, evaluator CONDITIONAL_PROCEED citing the ruling). Follow that precedent exactly. If it does not carry over (for example, REQ-W-13 rejects the verdict), escalate rather than improvise a new override path.

The worker may ask ESC-2 ahead of time, together with the PR's other questions, so the build does not stall for a cycle at PR time.

---

## 12. Startup-gap and affected sign-offs

**Was this a startup gap?** Partly. The suspension mechanism never had an expiry, because `review-by` only nudges. That should have been settled when SPEC-378 / #62 defined suspensions. The worker should annotate this as a `startup-artifact-gap` when it files the D-10 follow-up. I have not filed it, because this task is limited to this file.

**Affected sign-offs:** none invalidated.
- No code has been approved against a contract where suspension resolves dep-mapper LOW.
- The parked steps never passed 7b.
- Their existing risk-assessments were produced under the old prose, and they go stale anyway at re-entry (§11), because the range changes.
- Merged steps that never used `SUSPENDED: dep-mapper` (the repo had no suspension file) are untouched.
- [ARCH-R1] Architect concurs: no prior sign-off is orphaned. The round-1 changes (D-3 revision, D-15 to D-18) apply only to the new `suspended:` path, which no approved artifact has used. The one ongoing effect on unrelated steps is the repo-wide CONDITIONAL_PROCEED from the unchanged SPEC-82 WARN (§6). That changes their merge disposition, not their sign-offs.

**[AM-1] Startup gap and affected sign-offs.**

*Should this have been settled in the initial design?* Yes. Ruling A on #2214 (the disclosure must be visible text) was known before item 6 was written. The visibility rule should have been an allowlist from the start, rather than growing through five security rounds. The worker should record this on #2214 as a `startup-artifact-gap` annotation. I have not filed or annotated anything, because this task excludes it.

*Affected sign-offs.* The contract changed for behaviour that has already been built and reviewed, so these entries in `.claudetmp/signoffs/step2214-register.md` are **orphaned** for `validate_disclosure`, `validate_dep_trace` and their tests, and need re-review after the AM-1 build:
- code-review, APPROVED at `5d82e43ef` and `13c623a86`;
- unit-test, APPROVED rounds 2–3;
- ops, the 2026-11-17 entries;
- reliability, the delta entry.

security stays CONDITIONAL. Its last entry asked for this change, and it must re-review the AM-1 build in full, including D-20's narrowing. The architect must approve AM-1 (round 2 of 5) before coding.

These sign-offs **stand**, because AM-1 does not touch what they cover:
- the grammar and status classifier (§3);
- S0–S5 and S7;
- REQ-W-18's wiring (§5.4);
- `contract/gate-suspension.md`.

No merged code is affected: #2214 has not merged, and no parked step has used the disclosure.

**[ARCH-R2] Architect review of AM-1 (round 2 of 5): CHANGES REQUESTED.**

*Approved as direction.*
- D-19, the allowlist, is right. GitHub renders math and mermaid in the browser, after the markdown API returns its HTML. So a render-API check would not have caught the `$$\color{white}` route either, and it would make REQ-W-18 depend on the network. Record this reason in D-19 as well.
- D-20, leaving the suffix unchecked, is sound. CommonMark/GFM block parsing only runs forward. An open block after the section cannot reach back. Link-reference and footnote definitions are the only constructs that act backwards, and they need `[` in the section. The narrowing is not a loosening of ruling A. Ruling A is about the disclosure being visible. The body-wide scan was the TD's way of checking that, not the property itself, and it fails every real handoff today, because of the SPEC-82 recipe's `<default>`. No separate human ruling is needed before coding. The PR's human summary must still disclose the narrowing, and it already does.
- V9 is correct. Contract 7b(iii) requires a "structurally valid manual trace" and does not list the V-rules, so the contract text does not need to change.
- The §12 startup-gap and orphaned-sign-off analysis is correct.

*Must fix in round 3:*
- **AR2-1 (D-20's premise is not checked).** D-20 relies on "the checked prefix is the fixed AI-Submitted template", but nothing checks it. Add these prefix rules:
  - **P7.** Line 1 of the body, with trailing spaces removed, equals `## 🤖 AI-Submitted Pull Request`.
  - **P8.** The prefix has no other line matching `^#{1,6}( |$)`.
  - **P9.** The line directly before the disclosure heading is blank.

  P9 removes the one MEDIUM-confidence dependency: whether a GFM table, paragraph or multi-line link title is interrupted by an ATX heading. None of them survives a blank line. P7 also rules out front matter and a disclosure buried under arbitrary prefix content. All three hold for the orchestrator template at `oversight-orchestrator.md:97–113` with the D-20 placement. Of the 61 existing handoffs, 52 start with that exact line. The other 9 are older or escalated handoffs that opened no PR. P7 applies only where REQ-W-18 requires a disclosure, so a non-conforming body fails closed.
- **AR2-2 (section end does not need a GitHub-parity argument).** When a terminating heading follows the section, the section's last line must be Kind A. The template already ends with a blank line. Without this rule, a table ending at the section boundary depends on the heading interrupting it.
- **AR2-3 (R6 is wrong).** A col-0 `### x` matches item 2's end pattern, so it ends the section. It does not "fail closed" through R3. The outcome is still safe, because the required tokens, table and items after it fall outside the section, and items 2–4 fail. Correct the text, and add a T-D6 case with `### x` placed before the table.
- **AR2-4 (D-21 is broken by per-section V9).** V9 applies R5 to each trace section separately. A trace with a table in `## Items dep-mapper left untraced` therefore passes V9, and its disclosure then fails R5 with "more than one table". Ban Kind D lines in the Items section in V9, or apply R5 across both sections together.
- **AR2-5 (V9 boundary for R5(d)).** Define that the trace section's own heading line counts as Kind B for R5(d). Otherwise a trace table directly under its heading has no "line before".
- **AR2-6 (R3 is ambiguous).** State that the character immediately after `- ` must be in the R3 start set. Then `-     x` (a list item opening indented code) is rejected. Also say what happens to a bare `-` after trailing-space removal. After a paragraph line it is a setext underline. Reject it, and change T-D8's "`- ` + empty → valid" to match.

*Should fix (precision, no design change):*
- **AR2-7.** P6, the exactly-once rule, counts over the **whole** body, suffix included. Say so, and file it under item 1, not under the prefix rules.
- **AR2-8.** Two changes:
  - Item 5's fail-closed check and D-21's premise apply every section line rule (R1 and R4) to the `Authorized by:` value, not only R1.
  - R4: make the match case-insensitive, and catch the sign forms `:+1:` and `:-1:`. Only all-digit names stay residual (R-8).
- **AR2-9.** Three corrections:
  - D-20's "the section contains no `[`/`]`" has one exception, the Kind C literal. It is a complete inline link, and a definition cannot redirect it. State that.
  - `validate_dep_trace` should use R0 splitting for every V-rule, so that V9's `<k>` and the V1–V8 line numbers agree.
  - R-8 should note that `@name` in agent-written trace text notifies that user when the PR opens.

*Human ruling needed:* none for AM-1. ESC-2 (§11.1) is unchanged.

**[AM-1 R3] Response to ARCH-R2 (technical-design, round 3).** All nine findings are accepted. I disagree with none of them.

| Finding | Resolution | Where |
|---|---|---|
| AR2-1 | Added P7 (line 1 is the AI-Submitted heading), P8 (no other heading in the prefix) and P9 (a blank line before the disclosure heading). D-20's rationale now rests on P9 and forward-only parsing, and CONFIDENCE is raised to HIGH. The placement text now gives the counts: 52 of 61 handoffs pass P7, and the other 9 fail closed. | D-20, CONFIDENCE, §5.3 placement, P7–P9, T-D15 |
| AR2-2 | Added R7: the section's last line is blank when a heading follows. R5(d) now allows only blank or EOF after a table. | R5(d), R7, T-D16 |
| AR2-3 | Rewrote R6: a col-0 `#{1,6}` heading ends the section, and the outcome is fail-closed through items 2–4, not through R3. | R6, T-D6 |
| AR2-4 | Chose the ban: V9 rejects any table row in the Items section, and the disclosure's new R5(e) requires the one table to sit under the Callers heading. I preferred this to a joint R5, because it keeps item 3's table comparison unambiguous. | V9, R5(e), T-D10, T-D17 |
| AR2-5 | The trace section's own heading counts as Kind B for R5(d). | V9, T-D10, T-D17 |
| AR2-6 | R3 now requires a start character immediately after `- `. A bare `-`, and a `- ` with only trailing spaces, are rejected. Empty bullets are not allowed; write `- none`. T-D8 is corrected. | R3, T-D8 |
| AR2-7 | P6 is retired. The exactly-once rule is under item 1 and counts over the whole body. | item 1, P6, T-D6 |
| AR2-8 | Item 5 and D-21 apply R1 and R4 to the `Authorized by:` value. R4 is case-insensitive and catches `:+1:`/`:-1:`. Only all-digit names remain residual. | item 5, D-21, R4, T-D9, T-D13 |
| AR2-9 | D-20 states the Kind C exception. Every V-rule uses R0 splitting. R-8 notes that `@name` in a trace notifies that user. | D-20, V9, R-8, T-D17 |

*Startup-gap and sign-offs:* unchanged from the AM-1 analysis above. Nothing was coded against AM-1, so round 3 orphans no further sign-off.

**[AM-2] Startup gap and affected sign-offs.**

*Was this a startup gap?* Partly. ARCH-R1 saw the race and recorded it as residual R-7 rather than closing it. The fix-over-waive ruling (2026-11-13) made that residual unacceptable. The worker should annotate #2214's `startup-artifact-gap` with it.

*Affected sign-offs.* These are orphaned for S4 and REQ-W-18 and need re-review against §5.2.1, because the code they approved reads the unverified ref:
- code-review;
- security;
- reliability, which must also review R-10;
- ops, for the E-F1, E-F2 and E-F3 messages;
- unit-test, for group (g) and the extended T-A4.

These **stand**: the grammar and classifier (§3), the trace validator (§4), S0–S3, S5–S7, the disclosure (§5.3, AM-1), and the gate path, which is unchanged.

**[ARCH-R3] Architect review of AM-1 round 3 (round 3 of 5, 2026-11-18): APPROVED. The coder may implement AM-1.**
- **AR2-1 resolved.** P7–P9 hold on the orchestrator template (lines 97–113): line 1 is the heading, the only other prefix line starting `#` is none, and line 112 is blank. P9 removes the dependency on a heading interrupting a block. D-20's HIGH confidence is now justified: past a blank line, only P1–P3 constructs could carry, and those are banned.
- **AR2-2 resolved.** R7 is correct. R5(d) no longer allows "end of section" after a table, so a table at the boundary cannot be left relying on the heading to close it.
- **AR2-3 resolved.** R6 now matches item 2. T-D6 asserts that the outcome fails closed through items 2–4.
- **AR2-4 resolved.** The ban, together with R5(e), is the better choice than a joint R5. Item 3 then compares exactly one table, and D-21 holds by construction (T-D17).
- **AR2-5 to AR2-9 resolved** as stated in the response table.
- **Non-blocking note for the coder (no TD change needed).** When V9 applies R5(d) to a trace section, treat the end of the section as EOF, or do not. Either choice is fail-safe, because the §5.3 template inserts a blank line after the copied Callers section. Pin the chosen behaviour in T-D17 with a trace whose table runs directly into `## Items dep-mapper left untraced`.
- **R4's added `-` class** can reject time ranges such as `12:00-13:00` in trace text. That fails closed at trace time (V9), and it is acceptable.

Unchanged from ARCH-R2: no human ruling is needed for AM-1, and the PR must still disclose the D-20 narrowing. Security must re-review the AM-1 build in full. The orphaned sign-offs listed above must re-review against the AM-1 build. ESC-2 (§11.1) remains open.

**[ARCH-R4] Architect review of AM-2 (round 4 of 5, 2026-11-18): CHANGES REQUESTED.**

*Approved as direction.*
- AM-2 uses one remote comparison and reads the blob at the verified SHA, and it never fetches. That is the right shape. It does not change any refs, and it leaves no window between the check and the read (T-F7).
- Every error path returns `text=None` with an error message.
- `main_suspension_error` is required and keyword-only, so a caller that does not pass it cannot skip the freshness check (T-F8).
- The gate path is untouched (T-F9).
- **The network dependency is acceptable.** S4 already depends on the network for the `until-closed:` issue read (R-4), so this adds no new class of dependency. It fails closed, and it affects only steps that rely on the suspension. The human chose fix over waive for this pattern. AM-2 has no product, cost or retention consequence, so no human ruling is needed.

*Must fix in round 5:*
- **AR4-1 (the default branch still comes from a local ref an agent can write).** Step 1 takes `<D>` from the local `refs/remotes/origin/HEAD`. An agent can push its own branch carrying an added suspension, then run one `git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/<that branch>`. The local SHA then equals the remote SHA, and S4 passes against a branch that never went through the CODEOWNER-gated merge. That defeats D-16 without the work of repointing `origin` (R-5). AM-2 already makes a network call, so take `<D>` from the remote in the same call:
  - Run `git ls-remote --symref --exit-code origin HEAD`.
  - Parse the `ref: refs/heads/<D>\tHEAD` line and the `<sha>\tHEAD` line.
  - Compare that SHA with the local `refs/remotes/origin/<D>`.
  - If there is no symref line, return E-F2. Drop the fallback to `main` on this path.

  T-F2 to T-F5 must use this form. Add T-F10: local `origin/HEAD` repointed to a pushed branch that carries the suspension → not ok.
- **AR4-2 (R-7 is narrowed, not closed).** Freshness is checked when the evaluator or REQ-W-18 runs, not at merge. A revocation between that check and the merge is not caught. Today the bound is that every step evaluated while the file exists is CONDITIONAL_PROCEED, and so HUMAN_REQUIRED (§6, D-9). That bound disappears when the ESC-1 follow-up lands. Make three changes:
  - Reword R-7 to "narrowed", and state the remaining window and its current bound.
  - Add a constraint to §6 and D-9: the ESC-1 follow-up must not remove the human hold on suspension-resolved steps unless the overseer re-runs `--check-suspended-resolutions` before auto-merge.
  - Change the AM-2 header's "closes R-7" to match.
- **AR4-3 (consistency).** The D-16 row still describes the local `symbolic-ref` read. Update it to point to §5.2.1. Also, step 5 reads `path`, but the reader has no `path` parameter. State that it is the fixed `SUSPENSION_FILE`.

*Should fix (fail-closed either way, so these are about precision and denial of service):*
- **AR4-4.** `ls-remote` patterns match the end of a ref name. A pushed branch such as `x/refs/heads/main`, or `x/HEAD` under AR4-1, adds a second line, so "exactly one line" becomes a permanent E-F2 that an agent can trigger. Select the line whose ref field **equals** the expected name. Fail only if that line is missing or appears more than once. Use `re.escape` on `<D>` in the regex.
- **AR4-5.** Step 5 treats every `git show` failure as a missing blob. Report a missing path as `text=None, error=None` (for example, check `git cat-file -e <sha>:<path>` exit status, or match the "does not exist" stderr). Report a timeout or any other failure as a reader error. S4 fails either way. Only the message changes.
- **AR4-6.** R-10 should say that `GIT_TERMINAL_PROMPT=0` does not stop ssh passphrase or host-key prompts, or an askpass helper. Those are bounded by the 60 s timeout, which is enough. Do not force `BatchMode`, because it would override the operator's ssh configuration.

*Startup gap and sign-offs:* I concur with the AM-2 analysis. ARCH-R1 knowingly accepted R-7, so this is a `startup-artifact-gap` annotation. The listed sign-offs are orphaned for S4 and REQ-W-18, and the rest stand.

*Human ruling needed:* none for AM-2. The PR must disclose R-10 and the remaining R-7 window.

*Loop cap:* this is round 4 of 5. If round 5 does not converge, the architect escalates to the human instead of opening a sixth round.

**[AM-2 R5] Response to ARCH-R4 (technical-design, round 5 of 5).** All six findings are accepted, with no disagreement.

| Finding | Resolution | Where |
|---|---|---|
| AR4-1 | `<D>` and its SHA come from one `git ls-remote --symref --exit-code origin HEAD`. The local `origin/HEAD` is not read, and the `main` fallback is dropped on this path. A missing symref line gives E-F2. T-F1 to T-F7 are restated in this form. T-F10 is added. | §5.2.1 step 1, T-F1–T-F7, T-F10 |
| AR4-2 | R-7 is reworded to NARROWED, with the remaining check-to-merge window and its current bound (the SPEC-82 hold). §6 and D-9 now bind the ESC-1 follow-up to an overseer re-check before auto-merge, and note that the overseer also needs access to the step's artifacts. The AM-2 header and the §5.2.1 title say "narrows". | R-7, §6, D-9, header |
| AR4-3 | The D-16 row points to §5.2.1. Step 4 reads the fixed `SUSPENSION_FILE`, and the reader has no path parameter. | D-16, §5.2.1 step 4 |
| AR4-4 | ls-remote lines are selected by an exact second field `HEAD`, each line kind exactly once, and `re.escape(D)` is used elsewhere. T-F11 is added. | §5.2.1 step 1, T-F11 |
| AR4-5 | A missing path (`ls-tree` exit 0 with empty output) gives `text=None, error=None`. A timeout, a git error or a non-blob gives the new E-F4. T-F12 is added. | §5.2.1 step 4, E-F4, T-F12 |
| AR4-6 | R-10 notes that ssh passphrase, host-key and askpass prompts are bounded by the 60 s timeout, and that `BatchMode` is deliberately not forced. | R-10 |

*Startup gap and sign-offs:* unchanged from the AM-2 analysis. The same sign-offs are orphaned for S4 and REQ-W-18.

**[ARCH-R5] Architect review of AM-2 round 5 (round 5 of 5, 2026-11-18): APPROVED. The coder may implement AM-2.**
- **AR4-1 resolved.** The branch name and the SHA both come from one `ls-remote --symref --exit-code origin HEAD`. The local `origin/HEAD` is never read, and there is no `main` fallback. T-F10 reproduces the repointing attack and asserts that no `symbolic-ref` call is made. The `<D>` validation rejects names that start with `-` or contain `..`, so the `rev-parse` argument cannot be turned into an option or a range.
- **AR4-2 resolved.** R-7 is NARROWED, with the check-to-merge window and its temporary bound stated. The constraint in §6 and D-9 binds the ESC-1 follow-up. Technical-design's addition, that the overseer needs the step's `risk-assessment.md` and trace or else the hold stays, is correct and is binding. Without those files, the re-check would fail closed into a permanent hold, or be skipped.
- **AR4-3 resolved.** D-16 now points to §5.2.1, and the reader reads the fixed `SUSPENSION_FILE`.
- **AR4-4 resolved.** A line is used only if its second field is exactly `HEAD`, and each line kind must appear exactly once, so decoy branches are ignored (T-F11).
- **AR4-5 resolved.** `ls-tree -z` separates a missing path from E-F4. A non-blob entry also gives E-F4. An executable-mode (`100755`) file also gives E-F4. That fails closed, and it is acceptable.
- **AR4-6 resolved.**

*Human ruling needed:* none for AM-2. The PR must disclose R-10 and the remaining R-7 window. The worker must copy the §6 constraint into the ESC-1 follow-up issue when it files it. ESC-2 (§11.1) remains open. Security must re-review the AM-2 build together with AM-1. The orphaned sign-offs must re-review against the build.

**[AM-3] Startup gap and affected sign-offs.**

*Should this have been settled earlier?* Yes. The #1856 guard predates AM-1, and the AM-1 template's `#N` should have been checked against it. Add this to #2214's `startup-artifact-gap` annotation.

*Affected sign-offs.* Code-review, security and unit-test need re-review of `validate_disclosure` (item 5 and R8) and V9. The prompt-level text in orchestrator step 1a needs the worker-session edit. The others stand: AM-2's S4 freshness work and §3–§4 V1–V8 are untouched.

*Other closing-keyword exposure checked (AM-3).* I ran the real `find_closing_refs` on:
- the disclosure template's fixed text and the shipped `Authorized by:` value: no match;
- the orchestrator's AI-Submitted template (`oversight-orchestrator.md`, from `## 🤖 AI-Submitted` to `# Handoff — Step {N}`): no match;
- the AI-Submitted blocks of the 61 existing handoffs: matches only in step2204 and step2263 (deliberate `Closes #N` lines, which `--closes` declares) and in step2214, where the match is this defect.

The only uncontrolled source inside the disclosure is copied trace text, which R8 (through V9) now covers. Outside the disclosure, the free-text `{SECOND_REVIEW_STATUS}` cell could contain "fixed #N". That is the existing submit_pr.sh guard's job and is out of AM-3's scope.

**[ARCH-AM3] Architect review of AM-3 (AM-3 round 1 of 5, 2026-11-18): APPROVED, with one architect-applied change.**

*Round count.* AM-3 starts its own count at round 1 of 5. The cap counts critique rounds **without resolution**. The AM-2 loop resolved at round 5 (ARCH-R5). AM-3 is a separate defect: a conflict with the existing #1856 guard, found at the submit gate. It is not AM-2 failing to converge. The pattern is still worth a human's notice: this TD has needed three amendments after approval, each found by a later gate (security, second review, submit). Disclose it in the PR's human summary. Two more consecutive rounds on AM-3 without resolution would be an escalation trigger, not a reason to restart the count.

*Why the fix is right, and more than friction.* GitHub's own grammar accepts `closed: #N`, keyword then colon then reference. So the AM-1 form `until-closed: #2162` would have closed #2162 on merge, and ended the suspension, even without the guard. The guard turned a silent loss of authorization into a refusal. `issue N` contains no reference GitHub or the guard recognise. I checked `_MAIN` in `closing_keywords.py`: "closed" can be followed by an optional `:`, and then the reference must be a URL, `o/r#N`, `GH-N` or `#N`. A URL would not work as a replacement either, because `until-closed: https://github.com/…/issues/N` matches. Item 5 compares the number as an integer against the `#N` that stays in `contract/gate-suspension.md`, which is not a PR body. That is consistent with D-21.

*R8 is sound.* It reuses the real guard grammar instead of copying it, so the two cannot drift apart. It loads the module by path and fails closed if loading fails. The `"_/_"` slug makes every match an error, and `find_closing_refs` returns cross-repo refs with an `o/r#N` key, so they are not dropped. Joining the section lines covers a keyword at the end of one line and the reference at the start of the next. Applying R8 through V9 keeps D-21, because trace text fails at trace time. `closing_keywords.py` ships wherever `submit_pr.sh` does, since `submit_pr.sh` refuses to run without it, so consumers are not left failing closed permanently. T-K3, which runs the real guard over a generated handoff, is the right regression pin.

*Architect-applied change (§9 row 9, marked [ARCH-AM3]).* AM-3 limited the until-closed rule to the disclosure and handed the rest to the guard. But the guard's refusal text invites `--closes` ("If it IS intended, pass --closes"), and that is exactly the wrong move for the until-closed issue. Row 9 now states the rule for the whole PR: title, body and every commit message in the range. On refusal, always reword. **Live instance:** the squashed commit message of `a95650565` contains `until-closed #2162`, and I confirmed the real guard CLI exits 1 on it (key `2162`). The worker must reword that commit message before submitting. Adding `--closes 2162` would close #2162 on merge.

*Non-blocking.* `issue 2162` is not an autolink, so the human loses the clickable link inside the disclosure. That is acceptable. The suspension file and the suffix can carry the link. A mechanical guard, where `submit_pr.sh` refuses `--closes N` when N is the active suspension's until-closed issue, would back up the prose rule. That is a follow-up for the worker to consider; it is outside this step's 12 files.

*Startup gap and sign-offs.* I concur with the AM-3 analysis: this goes into the `startup-artifact-gap` annotation. Code-review, security and unit-test must re-review item 5, R8 and V9.

*Human ruling needed:* none.


**[AM-4] Startup gap and affected sign-offs (#2392).**

*Should this have been settled in the initial design?* Yes. ARCH-R1 wrote D-16 because the working-tree suspension file is agent-writable. The same reasoning applies to the manifest, which is the other D-7 input, and D-17 should have pinned it too. Add this to #2214's `startup-artifact-gap` annotation. I have not filed or annotated anything, because this task is limited to this file.

*Affected sign-offs.* The contract changed for behaviour that has already been built and reviewed. So these `.claudetmp/signoffs/step2214-register.md` entries are **orphaned** for S3's manifest input, `cmd_check_suspended_resolutions` and REQ-W-18, and must re-review the AM-4 build:
- code-review, the latest APPROVED entry (AM-3);
- security, at `afb984d3b`, because AM-4 changes an authorization input;
- test-unit, round 11;
- reliability, the latest delta. G3 and G5 add two bounded local git reads, with no network call.

These **stand**:
- ops: there are no new operator-visible lines except E-G1 to E-G4. Ops should still confirm their wording, but this is not a re-review of AM-2.
- AM-1's allowlist (§5.3), V1–V9, AM-2's §5.2.1 reader and AM-3's R8: AM-4 does not change them.
- The grammar and status classifier (§3).

The second review must be re-run full-range on the AM-4 build (SPEC-219).

*Human ruling needed:* none expected, because AM-4 only tightens. The architect must rule on D-22.

**[ARCH-AM4] Architect review of AM-4 (AM-4 round 1 of 5, 2026-11-20): APPROVED WITH TWO ARCHITECT-APPLIED CHANGES.**

*Round count.* AM-4 is a new defect class (an unpinned D-7 input), found by the full-range second review, not AM-3 failing to converge, so it starts at round 1. This is the fourth post-approval amendment, each found by a later gate. The PR's human summary must say so (as ARCH-AM3 required for three).

*Why the core design is right.* The OR rule is the correct monotone combination: the default-branch flag is the CODEOWNER-reviewed reference, and the head flag can only add a gate. Reading the default manifest at `default_read["sha"]` (no second `ls-remote`, no ref name) inherits AM-2's freshness without a new window. G4's byte-level, direction-blind comparison is right: a direction-aware comparison would need the very parser whose blind spots are the problem, and an uncommitted tightening costs only a commit. G1 before any manifest read, and every error path returning `flag=True`, make the enumerated fail-closed list in item 5 complete for the reads themselves. Removing `manifest_path` from `_check_dep_mapper_suspension` is right: it is D-6's "fixed paths only" rule, and the parameter was a second, unpinned route to the same flag. Keeping `--manifest` for the other REQ checks is correctly out of scope and disclosed in R-5.

*D-22 ruling.* The polarity is approved. Strict "unlisted → True" on the default read would gate every new step, since a step's manifest entry normally lands on its own branch, and that would silently override the #2174 ruling for exactly the steps it was meant to cover. The head read keeps "unlisted → True", so a new step still has to be declared in a committed, CODEOWNER-reviewed `contract/**` change. But D-22 as written was not a pure tightening:
- **AR-AM4-1 (applied).** §5.2.2 item 1 said `None` is returned wherever the current code reaches `if not target`. That branch is also reached when there is no `steps:` block, so the default read would have turned "no `steps:` block" into False, contradicting D-22 and T-G8. `None` now means a `steps:` block was entered.
- **AR-AM4-2 (applied).** The scanner's safety rested on "not found → True". D-22 removes that on the default read, so any gated entry the scanner cannot see becomes False there, and a committed branch rewrite of that entry to canonical `false` lowers the gate. This is the re-id concern in its real form: not renaming the step, but rewriting an entry the default-branch scan misses. I reproduced three such misses at `99e40eea0` (folded id, indented `steps:`, tab-indented item). The fix makes "not listed" on the default read conditional on canonicality: the id appears nowhere in the raw text and every parsed id is a plain scalar. T-G13 pins it.
- **AR-AM4-3 (residual, disclosed in R-5).** A plain re-id, running under another step's id, does not depend on D-22. Reusing an existing non-gated id works under either polarity and needs no manifest change, because the step id is not bound to anything the agent does not write. It predates AM-4, AM-4 does not widen it, and it must be disclosed in the PR.

*Non-blocking.* (1) G4 compares raw blob bytes with working-tree bytes, so a clone with `core.autocrlf` or a `.gitattributes` eol/filter on the manifest fails E-G2 permanently. That is fail-closed friction, not a hole; add one sentence to the E-G2 operator guidance if ops agrees. (2) The "a branch can only make the gate stricter" claims in the header and in Human Review Required are true per step id after AR-AM4-1/2. Read them with AR-AM4-3.

*Startup gap and sign-offs.* I concur with the [AM-4] analysis above: annotate #2214's `startup-artifact-gap`. The orphaned sign-offs listed there (code-review, security, test-unit, reliability) must re-review the AM-4 build, including AR-AM4-1/2. Security must specifically confirm the AR-AM4-2 token regex and the T-G13 cases. The second review must be re-run full-range (SPEC-219).

*Human ruling needed:* none. With AR-AM4-1 and AR-AM4-2 in, AM-4 only tightens. AR-AM4-3 is a disclosure, not a loosening.

**[AM-4 SEC-R1] Security round 1 hardening (worker-applied, pure tightening).** Two changes, both in `scripts/oversight/suspension_manager.py`. (1) CWE-1286: the AR-AM4-2 canonical-text check on the default-branch read now treats an id that starts with a digit, `+`, `-` or `.` as canonical only if it fullmatches `0|[1-9][0-9]*`. So `007`, `0x7`, `0o7`, `0b111`, `1_0`, `+7`, `7.0` and `1e1`, which a YAML parser could read as another step's numeric id, fall back to gated. Ids that start with a letter are unaffected. (2) CWE-807: `git ls-tree` in `read_manifest_gate_at` and in `read_default_branch_suspension` now passes `--full-tree`, so the read no longer depends on the caller's working directory (`git show <sha>:<path>` was already root-relative). Tests cover each alias form, canonical `0`/`7` controls, and a read from a repo subdirectory.
