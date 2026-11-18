# TECHNICAL DESIGN — #2214: time-boxed suspension of dep-mapper `Data confidence: LOW` as a blocker

**Status:** ARCHITECT APPROVED WITH CHANGES (round 1 of 5, 2026-11-06). The architect applied the changes directly; they are marked **[ARCH-R1]**. Coding may start. ESC-2 must be answered before the build PR is opened, and only if dep-mapper reports LOW on this step (§11.1).
**Amendment AM-1 (2026-11-18, technical-design; PENDING architect review, round 2 of 5):** §5.3 item 6 changes from a denylist to an allowlist (D-19, D-20). The changes touch §4.2, §4.3 (new V9), §4.5, §5.3, §8 (R-8, R-9), §9 rows 1, 8 and 9, §10 (new group (f)) and §12. They are marked **[AM-1]**. The coder must not implement AM-1 until the architect approves it.
**[ARCH-R2] Architect review of AM-1 (round 2 of 5, 2026-11-18): CHANGES REQUESTED.** The direction (D-19, D-20, D-21, V9) is approved. Findings AR2-1 to AR2-9 are in §12 and must be resolved by technical-design in round 3. Coding of AM-1 stays blocked until then.
**[ARCH-R3] Architect review of AM-1 round 3 (round 3 of 5, 2026-11-18): APPROVED.** AR2-1 to AR2-9 are resolved (§12). The coder may implement AM-1. Security must re-review the build in full.
**[AM-1 R3] Round 3 (2026-11-18, technical-design): AR2-1 to AR2-9 addressed. PENDING architect review, round 3 of 5.** The response is in §12, "[AM-1 R3] Response to ARCH-R2". The changes are marked **[ARCH-R2 AR2-n]**. Coding of AM-1 stays blocked until the architect approves.
**[AM-2] Amendment AM-2 (2026-11-18, technical-design; PENDING architect review):** the default-branch freshness check (§5.2.1) **narrows** R-7 [ARCH-R4 AR4-2]. A window remains between the check and the merge (see R-7). It was triggered by the full-range second review at `54f271235`: codex request_changes, HIGH CWE-362 at `suspension_manager.py:751`. REQ-W-08 blocks on it, and the human chose fix over waive for this pattern (ruling A, 2026-11-13). AM-2 touches D-9, D-16, §5.2, §5.2.1 (new), §5.4, §6, §8 (R-7 narrowed, R-10 new), §9 rows 1–2 and §10 group (g). Round 5 [ARCH-R4] applies AR4-1 to AR4-6. Change class `additive`: it is a tightening, with one new required keyword argument and no loosening. RISK: HIGH (it adds a network dependency to a gate-resolution path). CONFIDENCE: HIGH. BLAST RADIUS: the `--check-suspended-resolutions` (evaluator 7b(iii)) and REQ-W-18 paths only.
**[ARCH-R4] Architect review of AM-2 (round 4 of 5, 2026-11-18): CHANGES REQUESTED.** The approach is approved. Findings AR4-1 to AR4-6 are in §12. Coding of AM-2 stays blocked until they are resolved. AM-1 remains approved and may be coded independently.
**[ARCH-R5] Architect review of AM-2 round 5 (round 5 of 5, 2026-11-18): APPROVED.** AR4-1 to AR4-6 are resolved (§12). The coder may implement AM-2. The loop converged within the cap.
**[AM-2 R5] Round 5 (2026-11-18, technical-design): AR4-1 to AR4-6 addressed. PENDING architect review, round 5 of 5, the last before human escalation.** The response is in §12, "[AM-2 R5] Response to ARCH-R4".
**[AM-3] Amendment AM-3 (2026-11-18, technical-design; PENDING architect review):** the disclosure's until-closed value is written as `until-closed: issue N`, not `#N`. It was found at the final submit gate: `scripts/automation/closing_keywords.py` (#1856, run by `bootstrap/submit_pr.sh`) reads `until-closed: #2162` as "closed #2162" and refuses the PR. Declaring it with `--closes 2162` would close #2162 on merge and end the suspension. AM-3 changes §5.3 (template, item 5, item 6 required values, new R8), V9, §9 row 9 and §10 group (h). Change class `clarifying`/`additive`: no rule is loosened, and one rule (R8) is added. RISK: MEDIUM. CONFIDENCE: HIGH. Every form was checked against the real guard. BLAST RADIUS: the disclosure template, `validate_disclosure`, V9, and orchestrator step 1a.
**[ARCH-AM3] Architect review of AM-3 (AM-3 round 1 of 5, 2026-11-18): APPROVED WITH ONE ARCHITECT-APPLIED CHANGE** (§9 row 9, the whole-PR rule). The details and the round-count ruling are in §12. The coder may implement AM-3.
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
| D-17 | **[ARCH-R1] Tier and human gate are re-derived, never only passed in.** The effective tier = max(`--tier`/`risk_tier`, `validated_tier:` from `risk-assessment.md`). An absent or unparseable `validated_tier` counts as CRITICAL, so S3 fails. Effective `human_gate_required` = the passed flag OR the manifest's flag for the step (read with the same parser as REQ-W-18, from `contract/step-manifest.yaml`; absent → False). | The caller (the evaluator, an LLM; or the worker's `--risk-tier` on `pr_readiness`) supplies these values. A caller that passes `--tier HIGH` on a CRITICAL step must not be able to clear S3. This is the effective-human-gate rule (`oversight-evaluator.md` "Effective human gate (re-derived, not trusted …)") applied to the new path. |
| D-18 | **[ARCH-R1] The parser cannot fail open.** The CLI counts raw lines in `risk-assessment.md` matching `^\s*resolution:\s*suspended:` and compares the count with the parsed findings that have a `suspended:` resolution. A mismatch → FAIL (S0). `applies` is true if either count is non-zero, or if any parsed finding has `source: dep-mapper`. The header `base_sha`/`head_sha` must equal `--range`, else FAIL. | A hand-rolled block parser that misses an entry would report `applies=False`, which is PASS. The cross-check turns a parser miss into a FAIL. The range check stops a stale assessment from another step from being used, even when the CLI is run on its own, outside REQ-W-04. |
| D-19 | **[AM-1] The disclosure section is checked against an allowlist, not a denylist.** Every raw line from the disclosure heading to the end of its section must match the line grammar in §5.3 item 6 (R0–R7). The grammar uses a closed character set and closed line shapes, so any construct not listed is rejected. | Security found five bypasses in a row: link-reference definitions, a comment opener inside a code span, multi-line link titles, GitHub math, and rich-render fences nested in list items. Each was patched with one more denylist rule. Every GitHub render extension is a new way to hide text, so a denylist cannot converge. An allowlist bounds the residual to inline syntax built from the allowed characters (R-8). Rendering through the GitHub markdown API was the other option. It was rejected for two reasons. First, GitHub renders math and mermaid in the browser, after the markdown API has returned its HTML, so a render-API check would not have caught the `$$\color{white}` route either [ARCH-R2]. Second, REQ-W-18 would need the network, and REQ-W-18 must stay deterministic and offline. |
| D-20 | **[AM-1] Outside the section, only the lines *before* the heading are checked, and only for constructs that can swallow a later heading. Lines after the section are not checked.** The orchestrator places the section directly after the AI-Submitted block, so the checked prefix is that fixed template. [ARCH-R2 AR2-1] That premise is enforced, not assumed: P7 requires line 1 to be the AI-Submitted heading, P8 allows no other heading in the prefix, and P9 requires a blank line directly before the disclosure heading. | P9 means nothing in the prefix needs an ATX heading to interrupt it. Paragraphs, tables, list items, blockquotes and multi-line link titles all end at a blank line. Only an open fenced block, a math block or an HTML block can carry across a blank line, and P1–P3 ban the openers of all three. Content after the section cannot change how the section renders. CommonMark/GFM block parsing runs forward only. The section's last line is blank when a heading follows it (R7). The section contains no `[`/`]`, so later link-reference or footnote definitions have nothing to resolve. The one exception is the Kind C attribution literal [ARCH-R2 AR2-9]. It is a complete inline link `[text](url)`, not a reference link, so no definition can redirect it. A body-wide scan adds no safety. It also caused false positives: 4 of the 61 existing handoffs, and the §5.3 SPEC-82 recipe line on every step. |
| D-21 | **[AM-1] Copy invariant.** Suppose a trace passes V1–V9, the suspension's `Authorized by:` value passes R1 and R4 [ARCH-R2 AR2-8], the handoff's line 1 is the AI-Submitted heading, and the orchestrator fills the §5.3 template exactly, copying the two trace sections unchanged and placing the section per D-20. Then `validate_disclosure` passes. A test pins this (T-D1). | A disclosure failure should always mean someone deviated from the template, never that a faithful copy was rejected. V9 moves every content failure back to trace time. |

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

- `applies` is True iff at least one finding has a `suspended:` resolution, any finding has `source: dep-mapper`, or the raw count in S0 is non-zero (D-18).
- **S0 (whole file) [ARCH-R1].** The raw `resolution:\s*suspended:` line count equals the parsed count, and the header `base_sha`/`head_sha` equal the range (D-18). Otherwise `ok=False`.
- **Effective tier and human gate [ARCH-R1]** are computed once, before S3, as D-17 specifies: the `tier` argument max'd with the header's `validated_tier:` (absent or unparseable → CRITICAL), and the flag OR'd with the manifest.
- `ok` is True iff S0 passes, S7 passes, and every `suspended:` finding passes **all** of the following:
  - **S1.** `source == "dep-mapper"` and gate `== "dep-mapper"` (D-8).
  - **S2.** `path == dep_trace_path(step)`.
  - **S3.** Not behind the effective human gate. Fail if the effective tier is CRITICAL or the effective `human_gate_required` is true (D-7, D-17).
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
- It reads fixed paths only: `.claudetmp/oversight/validators/risk-assessment.md`, `dep_trace_path(STEP)`, `.claudetmp/oversight/step{STEP}-handoff.md`, `contract/gate-suspension.md` (working tree), `git show <default>:contract/gate-suspension.md` (D-16; [AM-2] read at the SHA verified against `git ls-remote origin`, §5.2.1) and `contract/step-manifest.yaml` (D-17). There is no flag that overrides any of these paths, the date, the issue state, or the remote lookup.
- Output is `APPLIES=yes|no`, `RESULT=ok|fail`, and one `ERROR=<id>: <msg>` line per error.

| Result | Exit |
|---|---|
| ok, or not applicable | 0 |
| usage error, git failure, or risk-assessment.md missing | 2 |
| fail | 4 |

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

`_check_dep_mapper_suspension(repo_root, manifest_path, step, base_sha, head_sha, risk_tier) -> CheckResult("REQ-W-18", ...)`, appended to the `checks` list after REQ-W-14.

- It loads `suspension_manager.py` by file path (`importlib.util.spec_from_file_location`), as the tests do. A load failure → FAIL, which fails closed.
- `risk-assessment.md` absent → PASS ("not applicable; REQ-W-04 owns absence"). This avoids reporting the same gap twice.
- `changed_files` comes from `git diff --name-only base..head`. A failure → FAIL.
- `human_gate_required` is read from the step manifest. A new helper mirrors `gate_compliance.gates_required`'s parsing, and an absent manifest or flag gives `False`. The tier is `risk_tier`, which [ARCH-R1] `check_suspended_resolutions` raises to the validated tier (D-17), because the worker supplies `--risk-tier` itself.
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
| 1 | `scripts/oversight/suspension_manager.py` | coder | §3, §4.3–4.4, §5.1–5.3. Module docstring: add the new flags and CLI modes. The ratchet sentence stays: no code path writes a SUSPENDED line. [AM-1] V9, and §5.3 items 1, 2 and 6 (R0, P0–P5, P7–P9, R1–R7). Remove the `_visible_markdown` call from `validate_disclosure`. [AM-2] §5.2.1: `read_default_branch_suspension`, `_default_ls_remote`, the `_git` `env` overlay, the required `main_suspension_error` argument and the S4 error substitution. |
| 2 | `scripts/automation/lib/pr_readiness.py` | coder | REQ-W-18 (§5.4). [AM-2] Use `read_default_branch_suspension` and pass `main_suspension_error` (§5.2.1). |
| 3 | `tests/oversight/test_suspension_timebox.py` (new) | unit-test / coder | §10. Covers both modules. Existing `test_suspension_manager.py` and `test_pr_readiness.py` must still pass unchanged. |
| 4 | `contract/gate-suspension.md` (new) | top-level worker session | §7, verbatim |
| 5 | `contract/OVERSIGHT-CONTRACT.md` | worker session | §7, after 7b: one sub-item 7b(iii) stating §5's rule, D-7 and D-8. Also one sentence: only status `active` counts as suspended (D-4), with the D-2 date semantics. |
| 6 | `.claude/agents/risk-assessor.md` | worker session | Replace Phase-3 item 2's two bullets with §1 step 2. Add the resolution form as an example under the `blocking_findings` schema. |
| 7 | `.claude/agents/oversight-evaluator.md` | worker session | (a) Gate-suspension handling: a role counts as suspended only if `--suspension-status <role>` exits 0. (b) 7b(ii): a `suspended:` resolution is resolved only if `--check-suspended-resolutions N --range B..H --tier <validated> --human-gate-required <manifest>` exits 0. Any other exit → COMPLIANCE FAIL, listing the ERROR lines. (c) [ARCH-R1] **No SPEC-82 change** (ESC-1 deferred, §6). (d) Line 706 is unchanged. (e) [ARCH-R1] 7b(ii): a `source: dep-mapper` finding with `resolved: …` → COMPLIANCE FAIL (D-15). The CLI reports it too, but the prose rule must say so, because `--check-suspended-resolutions` is only consulted when a `suspended:` or dep-mapper finding exists. |
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

