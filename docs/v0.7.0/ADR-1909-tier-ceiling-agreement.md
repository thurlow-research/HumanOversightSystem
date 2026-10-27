# ADR-1909: One ceiling tier per PR head. CI's trusted, scoped scorer sets a floor that cannot be lowered. The overseer's own assessment can only raise the tier, and only through its attributed, head-bound review. `compute_tier_for_pr` stays the single source of truth, and the overseer runs it before it posts

**Status:** APPROVED WITH AMENDMENTS. AD-1 to AD-9 bind `technical-design`. AR-1 to AR-9 (§5) amend `REQUIREMENTS-1909-tier-ceiling-agreement.md`. They are recorded here and **not** applied in place: this cycle's task limits the architect to writing this one file. TD must treat each AR as overriding the requirement it names.

Some decisions are **PROVISIONAL**:
- AD-5 (function scoping) depends on ESC-1 and ESC-2.
- AD-6 (the overseer's upward-only claim) depends on ESC-3 and ARCH-ESC-2.

S1 depends on no ESC and can be designed and built now (§4).

No ESC answer and no agent-side waiver can relax these parts:
- AD-2: ceiling-tier code runs from the trusted base. PR content is fetched as data and parsed, never executed.
- AD-3: every new input fails closed, and every fallback only raises the tier.
- AD-6: agent-supplied tier information may only **raise** the ceiling tier, never lower it. The caller's `--tier` can no longer lower the tier `submit-verdict` enforces.
- AD-8: CI remains the **only** enforcement point. The overseer-side computation is a pre-check: its integrity affects liveness (whether the two sides agree), never safety.

**Date:** 2026-10-18
**Author:** architect (autonomous worker cycle). No human was present, so open decisions appear as ESC or ARCH-ESC items, each with a recommended default.
**Issue:** #1909 (filed by the overseer during PR #1907). Related: #973, #1426, #1427, #1657, #1791. · **Milestone:** v0.7.0
**Risk tier:**
- Build overall: **HIGH**. It changes the computation behind `OVERSEER_CEILING`, a CORE safety threshold, and the behaviour of two required checks.
- S1, S2, S3: **HIGH**, and **HUMAN_REQUIRED** (`scripts/framework/**`). `security-reviewer` is mandatory, and second review runs at HIGH+.
- S4: **MEDIUM** computed, and **HUMAN_REQUIRED** (`scripts/oversight/run_validators.sh`, `scripts/framework/**`).
- S5: **LOW** computed, and **HUMAN_REQUIRED** (`.claude/agents/**`).

**Inputs:** `docs/v0.7.0/REQUIREMENTS-1909-tier-ceiling-agreement.md` (VF-1 to VF-10, REQ-1 to REQ-12, NFR-1 to NFR-4, ESC-1 to ESC-3), read in full. Files read for this ADR at `8eb122060`:
- `scripts/framework/require_tier_ceiling.py` (whole);
- `scripts/framework/require_overseer_approval.py:135-230`;
- `scripts/framework/audit_predicate.py:1-140` (patch parsing);
- `scripts/framework/protected_surfaces.txt` (whole);
- `scripts/automation/pr_review_cli.py:455-480,560-645,890-975`;
- `scripts/automation/lib/merge_config.py:53-90`;
- `scripts/automation/lib/merge_authority.py:500-504,640-644`;
- `scripts/automation/lib/github.py:370-405` (`list_pull_files`);
- `scripts/oversight/run_validators.sh:33-35,60-95,295-340,420-530`;
- `scripts/oversight/validators/schema.py:55-110`;
- `scripts/oversight/validators/rn_calculator.py:187-330` (plus the import block);
- `scripts/oversight/validators/diff_size.py:59-222`;
- `scripts/oversight/changeset_logic.py:1-80`;
- `scripts/oversight/validators/regions.py` (the symbol list);
- the import lines of every validator under `scripts/oversight/validators/`;
- `.github/workflows/require-tier-ceiling.yml:1-92`;
- `bootstrap/pr_review.sh:25-94`;
- `.claude/agents/overseer.md:180-210,230-242,440-475,580-592`;
- `tests/framework/test_require_tier_ceiling.py` (the test list and its monkeypatch targets);
- `scripts/framework/setup_branch_protection.sh:126,171` (`dismiss_stale_reviews`).

I also ran `rn_calculator.py` on `tests/automation/test_hos_cron.py`. It gave `score=1.0` and `max_rn=32.0` at line 1420, then RN 10 at line 4628.

**Consumers:** `technical-design`, then `coder`, then the review chain. S5 is authored by the top-level session (CLAUDE.md, agent-definition edits).

**Explicitly does NOT re-litigate:**
- `pull_request_target` and the base-SHA checkout (`require-tier-ceiling.yml:46-48,75-77`; #972, #1299);
- ADR-1657 AD-2 (no `REQUEST_CHANGES`) and AD-3 (the reviewer-trigger scoping; see the AD-6 note);
- #621: a human approval alone never satisfies `require-overseer-approval`;
- `WEIGHTS`, `TIER_THRESHOLDS`, `_SCORE_HIGH_THRESHOLD`, `OVERSEER_CEILING` (requirements §3);
- #1791 (hunk scoping for **gates**).

---

## 0. Verification findings (tree at `8eb122060`)

### 0.1 Confirming pm-agent

I re-read every cited line.
- **VF-1, VF-2, VF-6, VF-7, VF-8, VF-9 and VF-10 are CONFIRMED** at the cited lines. VF-2 is reproduced as stated.
- **VF-3 is CONFIRMED**, with one nit: the composite is assigned at `run_validators.sh:484`, and `:485-488` is the tier mapping. The correction pm-agent made stands: the overseer's RN dimension also scores whole files (`:306-310`), so the real difference is aggregation.
- **VF-4 is CONFIRMED.** `merge_authority.py:502` takes `risk_tier` as an input, and `:641` compares it.
- **VF-5 is CONFIRMED.** `git diff --name-only "$DIFF_REF"` (`run_validators.sh:83`) compares against the working tree.

### 0.2 Architect findings (these change the design)

**AF-1 (HIGH): the gate resolves the file list and the head SHA separately.**
- `get_changed_files` (`:114-116`) reads `gh pr diff --name-only`.
- `_pr_head_sha` (`:177-182`) is called later, inside `_fetch_head_python` (`:197`).
- If a push lands between the two calls, the gate scores the new head's content against the old head's file list. A file added by the new push is then never scored.
- AD-3 pins one head SHA, reads it before and after the file list, and fails closed if the two reads differ.

**AF-2 (HIGH): a changed file that fails to parse is silently dropped today.**
- `rn_calculator.analyse_files` (`:259-305`) keeps the signal from the files that did parse and records a parse error only as a checklist line.
- The gate reads only `score` (`require_tier_ceiling.py:260`). A changed `.py` file the runner's Python cannot parse (for example, newer syntax) therefore contributes nothing.
- This fails open, against REQ-7. AD-3 adds a strict-parse mode in S1.

**AF-3 (MEDIUM): deletion is inferred from the error text.**
- `_fetch_head_python` treats any failure whose stderr contains `404` or `not found` as "deleted at head" (`:213-216`).
- A ref that is not found after a force-push is skipped the same way, which fails open.
- The files API reports `status: removed` explicitly. AD-3 skips a file only on that status, and treats a 404 on any other status as exit 2.

**AF-4 (MEDIUM): the path-escape guard skips silently.**
- `:202-203` uses `continue`. Git paths cannot escape, so this is defence in depth. Even so, a guard that fires must fail closed, not drop the file (AD-3).

**AF-5 (HIGH): the composite is not reproducible as a subset.**
- `run_validators.sh:457-463` divides the weighted sum by the total weight of the validators that **succeeded**. A missing or errored validator therefore shrinks the denominator rather than counting as risk.
- A composite computed in CI with a different toolset is a **different number**, not a subset of the same one. Running radon, bandit, ScanCode, `issue_query` and `prompt_audit_risk` there would also break NFR-1 and NFR-2. Only `rn_calculator`, `function_metrics`, `n1_detector`, `migration_scorer`, `hallucination_surface`, `portability_check` and `shell_logic_check` are stdlib-only and offline.
- This is why AD-6 does not recompute the composite in CI (ESC-3).

**AF-6 (MEDIUM): the two sides can run different scorer versions.**
- CI checks out the event's `base.sha` (`require-tier-ceiling.yml:77`). Reruns replay the original event (`:39-43`). So CI's scorer is the base at the last `pull_request_target` event.
- The overseer's `pr_review_cli` loads `require_tier_ceiling.py` from its own clone (`pr_review_cli.py:468`), which is normally `main`'s tip.
- If a scorer change lands between those two points, the sides can disagree. AD-7 makes this visible by having both sides report a `scorer_digest`. It is residual R-2.

**AF-7 (MEDIUM): `rn_calculator` emits no function span.**
- `_collect_functions` (`:199-206`) records `start_line = node.lineno`, which is the `def` line and excludes decorators. It records no end line.
- Function scoping needs `end_lineno` and a start that includes decorators. AD-5 adds both.

**AF-8 (LOW): the `rn_calculator` task-class floor never reaches CI.**
- The floor is set at `:388`, but only when `--task-class` is passed. The gate never passes it, and its input is agent-supplied. It is MEDIUM only, so it cannot matter at a HIGH ceiling.
- Under AD-6 it reaches the ceiling tier through the overseer's assessment.

**AF-9: reuse search (CLAUDE.md item 1; AGENTS.md "use the code").** I searched `scripts/` (recursively), `scripts/automation/lib/`, `bootstrap/` and `bin/`.

Not applicable:
- **`scripts/oversight/validators/regions.py`** parses agent CORE/PACK/PROJECT regions. It has no diff or hunk logic.
- **`scripts/oversight/changeset_logic.py`** classifies missing paths against a **local** git tree. CI has no head checkout, so it cannot apply.

Reused:
- **`require_tier_ceiling.py`'s own helpers:** `_gh` (and its `--paginate` idiom from `get_reviews`), `_fetch_head_python`, `_simplified_tier`, `_score_to_tier`, `_max_tier`, `tier_to_int` and `tier_exceeds_ceiling`. **`compute_tier_for_pr` stays the single source of truth** (its own banner at `:343-346` already says so), and the three consumers already load it by path.
- **`audit_predicate.extract_added_lines`** (`:90-121`) is the stateful unified-diff parse. It skips the header block structurally, which is the AD-17f fix for `+++` content lines. It returns text, not line numbers, so it cannot be called as it is. The new parser follows the same state machine, and a parity test (AD-5) keeps the two from drifting.
- **`diff_size.evaluate`** and the other validators are not imported by the gate (AD-6).

Rejected:
- **`scripts/automation/lib/github.py:list_pull_files`** has the right semantics, but it is outside `scripts/framework/**`. Loading it into the gate would add an unprotected module to the gate's trusted computing base. The gate's own `_gh --paginate` is reused instead.

---

## 1. Organizing principle

**One function, two kinds of input, one direction of trust.**

- **Trusted floor (`T_shared`).** This is computed by `compute_tier_for_pr` from base-pinned code, over head content fetched as data, for one pinned head SHA. CI computes it, and the overseer computes the same thing through the same function before it posts. Agreement is by construction: same code, same inputs, same output.
- **Upward-only assessment (`A`).** This is the overseer's own honest tier: the full composite with floors applied, the JS lane, and any risk-assessor promotion. It enters **only** through the overseer's GitHub-attributed review on the current head SHA. It can raise the tier, never lower it.
- **The ceiling tier** is `T = max(T_shared, A)`. The overseer's approve rule, `require-tier-ceiling` and the #1426 bypass all evaluate this same `T`.

Why this shape:
- CI cannot reproduce the composite (AF-5), and must not trust an agent's number to **lower** a tier (#1427).
- CI can, however, safely accept an attributed agent number that only **raises** the tier. The worst a wrong or hostile claim can do is require a human, which the overseer could already do by withholding approval.

---

## 2. Decisions

### AD-1: The single source of truth stays in `scripts/framework/require_tier_ceiling.py`. New pure helpers go in one sibling, `scripts/framework/tier_scope.py`. (BINDING. REQ-1, AF-9.)

- **`require_tier_ceiling.py` keeps the entry points:**
  - `compute_tier_for_pr(repo, pr) -> str | None`, unchanged, for back-compatibility. It returns `compute_tier_result(...).tier`, or `None` on fail-closed.
  - **New:** `compute_tier_result(repo, pr, *, head_sha=None) -> TierResult`. This is `T_shared` with its explanation (AD-7).
  - **New (S2):** `ceiling_tier(shared: TierResult, assessment: Claim | None) -> str`, which returns `max(shared.tier, assessment.tier)`. **This is the only place the max is taken.** A test pins that a lower claim never lowers the result.
- **`tier_scope.py`** is pure: no subprocess, no network, no `gh`, no filesystem write. This is the same discipline as `audit_predicate.py:13-16`. It holds:
  - `touched_new_lines(patch: str) -> frozenset[int] | None` (S3);
  - `render_claim(...) -> str` and `parse_claims(body: str) -> Claim | None | Malformed` (S2);
  - `assessment_tier(summary: dict, *, head_sha: str, files: list[str]) -> str` (S4).

  It is loaded by path, using the existing `_load_sibling_module` / `spec_from_file_location` idiom.
- **Why not a new top-level module.** `tests/framework/test_require_tier_ceiling.py` monkeypatches module attributes of `require_tier_ceiling` (`_fetch_head_python`, `_try_validator_summary`, `compute_tier`). Moving the computation would detach those patches, so REQ-12 could be met only by rewriting the suite. Keeping the entry point in place keeps the suite as the regression net.
- **Rejected alternatives:**
  - *A `scripts/framework/pr_tier.py` that replaces the module.* It breaks REQ-12, as described above.
  - *Importing `scripts/oversight/validators/*` in process.* Those modules mutate `sys.path` on import (`require_tier_ceiling.py:143-146`). `rn_calculator` stays a subprocess.
  - *Adding hunk parsing to `audit_predicate.py`.* That module is the sole authority for "audit-only" (ADR-035), and widening it couples two gates.

### AD-2: Trust boundary. Ceiling-tier code runs from the trusted base. PR content is data. (BINDING, not waivable. REQ-5, VF-10.)

- **CI.** Nothing changes: `pull_request_target`, a `base.sha` checkout, and head content via `gh api …/contents/<path>?ref=<head_sha>` written to a temp dir and **parsed** by base-checkout `rn_calculator.py`.
  - The workflow file is **not** modified by any slice.
  - The new inputs (the files API `status` and `patch`, and review bodies) are strings parsed by the base code.
- **Overseer side.** `pr_review_cli` loads `require_tier_ceiling.py` from its own clone (`:468`). The overseer clone is synced to `main` each cycle. The rules:
  - The overseer must not run tier code from a PR-head worktree. S5 states this in `overseer.md`.
  - The overseer's composite (input `A`) comes from **its main clone's** `run_validators.sh`, run over the PR's files. S4 stamps the validator commit, and `submit-verdict` refuses an assessment whose validator commit is not reachable from `origin/<base>`.
- **Why the overseer side is liveness, not safety (AD-8).** If the overseer's clone ran tampered tier code, the worst outcome is that it approves something CI then fails. That is a red gate, which is the #1907 symptom, and it cannot admit anything. The overseer side is not a second line of defence. It exists so the two sides agree.

### AD-3: Pinned inputs, the REQ-6 file set, and every new input fails closed. (BINDING, not waivable on direction. REQ-4, REQ-6, REQ-11, AF-1 to AF-4. Lands in S1 and is independent of every ESC.)

- **File set.**
  - The gate replaces `gh pr diff --name-only` with `GET /repos/{o}/{r}/pulls/{n}/files`, paginated with `_gh("api", "--paginate", …)`. Each record carries `filename`, `status`, `patch`, `previous_filename` and the additions/deletions counts.
  - This is the same merge-base-relative set `gh pr diff` reports (REQ-6). Base-only changes cannot enter it.
  - GitHub caps this listing at 3000 files. A listing that reaches the cap → exit 2. The PR size policy makes this unreachable in practice, but a truncated list must never count as complete.
- **Head pin.**
  - Read `pulls/{n}.head.sha` (H1), then list the files, then read the head SHA again (H2). H1 ≠ H2 → exit 2 on the gate, or a refusal on the overseer side, with the reason `head_moved_during_computation`.
  - Every content fetch uses H1.
  - On the overseer side, H1 must also equal `pre.head_sha`.
- **Deletion.** A file is skipped as deleted only when `status == "removed"`. A 404 on any other status → exit 2 (AF-3).
- **Path guard.** A path that is absolute or contains `..` → exit 2, not skip (AF-4).
- **Strict parse.** The gate calls `rn_calculator.py --strict-parse`, a new flag. In that mode, **any** parse error among the passed files sets `error`, and the gate fails closed (exit 2) (AF-2, REQ-7).
  - Without the flag, `rn_calculator`'s behaviour is unchanged, so the advisory `run_validators.sh` path does not move.
  - A file that is not valid UTF-8 at head is a parse error.
- **No precomputed summary.** `_try_validator_summary` is **removed** from the ceiling path (REQ-11, VF-8). No summary file is read by the gate or the bypass. The overseer's validator summary reaches the tier only as input `A`, with S4's binding.
- **Existing fail-closed paths are unchanged** (REQ-4): exit 2 on a head-fetch failure, on a validator error, and on missing `machine-accounts.env` keys; an unknown tier maps to CRITICAL.
- **Fallbacks only raise the tier, and each one prints a line** (REQ-4). In S3, a file whose patch is absent or malformed is scored whole-file (AD-5). There is no other fallback: every other unobtainable input is exit 2 or a refusal.

### AD-4: The overseer obtains `T_shared` before it posts, and `submit-verdict` no longer trusts `--tier` downward. (BINDING. REQ-2 first direction, REQ-3, VF-6. Lands in S1 and is independent of every ESC.)

- **New read-only subcommand.** `bash bootstrap/pr_review.sh compute-tier --pr <n> --app overseer` prints one JSON object: the AD-7 `TierResult` plus `ceiling` and `exceeds_ceiling`.
  - It lives in `pr_review_cli.py`, which is unprotected.
  - The wrapper's role check covers only `submit-verdict` and `request-reviewer` (`pr_review.sh:42-48`), so a new subcommand passes through unchanged. TD must confirm that `pr_review.sh` needs **no** edit. If it does, S1 gains `bootstrap/**`.
- **`submit-verdict` G1.**
  - It computes `T_shared = compute_tier_result(repo, pr, head_sha=pre.head_sha)` and sets `effective = max(T_shared, --tier)`.
  - `approve` with `effective > OVERSEER_CEILING` → exit 3. The `refusal_reason` is `above_ceiling_enforced_tier` when `T_shared` caused the refusal. It stays `above_ceiling_approve` when `--tier` alone caused it, so the existing W-tests keep their reason (REQ-12).
  - No POST is made in either case (REQ-2 AC(a)).
  - `T_shared` is `None` (fail-closed) → `approve` is refused with `enforced_tier_unavailable`. `comment` is still allowed, because withholding approval is always safe.
- **`--tier` stays required** (argv contract, TD-1657 §4.1). It is now only an upward input.
- **What changes for the #1907 shape right after S1.** The overseer is refused before it posts, then posts `comment`. The gate computes CRITICAL, so the #1426 bypass fires on a human approval. There is no red check and no dismiss-and-repost.

  Until S3, a hot-file PR therefore becomes HUMAN_REQUIRED cleanly rather than red. That is stricter than today's net outcome and is never looser (ARCH-ESC-3).

### AD-5: Scope of `T_shared`'s RN term is functions the PR changes, scored in full. (PROVISIONAL on ESC-1 = B and ESC-2 = function unit. BINDING on REQ-7's no-discount rules either way. Lands in S3.)

- **Touched lines.** `tier_scope.touched_new_lines(patch)` parses the API `patch` with the `extract_added_lines` state machine (structural header skip; one leading marker per line), plus a capturing hunk-header regex for the line numbers.
  - Every `+` line contributes its new-file line number.
  - Every run of `-` lines contributes the new-file lines immediately before **and** after the deletion point. Deleting code from inside a function changes that function.
  - Context lines contribute nothing. This avoids pulling in a neighbour through ±3 context lines.
  - The header's counts must match the body's counts. Otherwise the function returns `None` (malformed).
- **Function span.** `rn_calculator` records `span_start = min(node.lineno, *(d.lineno for d in node.decorator_list))` and `end_line = node.end_lineno` (AF-7).
  - A new flag, `--line-scope <json>`, maps each path to either a list of `[a, b]` ranges or `"all"`.
  - A function is **in scope** if its `[span_start, end_line]` intersects any touched line. Nested spans nest, so the functions enclosing a changed inner function are also in scope.
  - The RN term is `normalize(max in-scope RN, 0, 20)`. This uses the existing normalization in `rn_calculator`, not a copy.
  - Output adds `scope: {in_scope: [...], out_of_scope_max: {file, line, name, rn}}` for REQ-10.
- **Whole-file cases** (`"all"`). These raise the tier, print the reason, and are never skipped:
  - `status` is `added` (every line is touched anyway);
  - `status` is `renamed` (REQ-7: a move is a change; a renamed file moves every function in it);
  - the patch is absent, which GitHub does for large diffs;
  - `touched_new_lines` returns `None`.
- **Module-level code.** `rn_calculator` scores only functions, so module-level lines carry no RN either way. REQ-8's module-level clause is vacuous for the RN term (AR-6).
- **No configuration knob.** The scope mode is a module constant (`RN_SCOPE = "function"` or `"file"`). A config key would be a loosening lever that a PR could flip. Changing it is a protected-surface edit.
- **Parity test.** On a shared corpus, including `+++`-prefixed content lines, the `+` lines that `touched_new_lines` counts must match `audit_predicate.extract_added_lines`'s text one for one.

### AD-6: The overseer's assessment enters only as an upward-only, attributed, head-bound claim in its review. (PROVISIONAL on ESC-3 and ARCH-ESC-2. BINDING on "upward only". Lands in S2.)

- **Producer.** `submit-verdict`, for both `approve` and `comment`, appends a generated block to the body. The overseer never writes it by hand.
  - The block holds REQ-10's human-readable explanation, then exactly one final line:

    ```
    <!-- hos-ceiling-tier/1 assessment=<TIER> shared=<TIER> head=<40-hex> scorer=<12-hex> -->
    ```

  - `assessment` is `--tier` (or S4's summary-derived tier, whichever is higher). `shared` and `scorer` come from `T_shared`.
  - The wrapper's byte-identical-body dedupe guard sees the block as part of the body. That is correct, because a changed tier is a changed verdict.
- **Consumers** (both gates, through `ceiling_tier`):
  - **`require-tier-ceiling`**, approve case: `A` comes from the overseer's latest `APPROVED` review.
  - **`require-overseer-approval`**, #1426 bypass: `A` comes from the overseer's latest non-`DISMISSED` review whose `commit_id` equals the current head. The bypass fires when `ceiling_tier(T_shared, A) > OVERSEER_CEILING` and a human approval is present. This closes VF-7, including the JS-lane, composite-driven and promotion cases.
- **Acceptance rules for a claim:**
  - The review's `user.login` equals `BOT_OVERSEER_USERNAME`. Attribution is GitHub's, from the App installation token, and cannot be forged by a worker.
  - `head` equals both the review's `commit_id` and the pinned H1. A claim for another head is ignored, and the tier is `T_shared`.
- **Malformed claims.** More than one marker, an unknown version, or a tier outside `TIER_ORDER` → `A = CRITICAL`, which is upward and fail-safe.
  - This also neutralises a PR that plants a marker for the overseer to quote. A quoted marker either makes the count more than one, which gives CRITICAL, or is not on the final line, which also gives CRITICAL. It can only raise the tier.
- **An approval with no claim** (posted before S2, or a direct POST) → `A` is absent, so `T = T_shared`, and the gate prints a WARNING line. Absence carries no upward information, and requiring a claim would add a failure mode that protects nothing, since `T_shared` is still enforced.
- **Why this is safe** (the REQ-5 amendment, AR-3):
  - `max` makes `A` unable to lower `T`.
  - Only the overseer identity can author `A`.
  - A wrong-high `A` can only send a PR to a CODEOWNERS human. That is a stronger control than overseer approval, and #621 still holds, because the bypass still needs an overseer review on the PR.
  - A worker dismissing an overseer review removes `A`. That can only **stop** the bypass from firing, never admit a PR.
- **Reviewer trigger.** `request-reviewer` evaluates `evaluate_reviewer_trigger` with `effective = max(T_shared, --tier)`. This adds no trigger term. It feeds AD-3's existing `above_ceiling` and `critical_tier` terms the tier the gates enforce, so ADR-1657 AD-3 is not widened.

### AD-7: `TierResult` explains itself, on both sides. (BINDING. REQ-10. S1 adds the structure; S2 and S3 add fields.)

- `TierResult` is a frozen dataclass and serializes to JSON with these fields:
  - `tier`, `head_sha` and `merge_base` (from `GET …/compare/{base_sha}...{head_sha}`, for reporting only);
  - `files_scored` and `files_skipped` (each with a reason);
  - `terms`: `rn` (with `{file, line, name, rn}` for the function that set it), `structural`, and from S2 `assessment`;
  - `scope` (S3: in scope, and the out-of-scope maximum);
  - `fallbacks` (each `{file, reason}`);
  - `scorer_digest`: sha256 over the bytes of `require_tier_ceiling.py`, `tier_scope.py` and `rn_calculator.py` as loaded.
- **Gate stdout** prints each field on its own line. For the #1907 fixture after S3, it must print the RN-32 function as `out_of_scope_max` (REQ-10 AC).
  - When the claim's `scorer` differs from CI's own digest, the gate prints `NOTE — scorer drift (overseer <a>, CI <b>)`. This is diagnostic only (AF-6).
- **The overseer's verdict body** carries the same explanation through AD-6's generated block.

### AD-8: CI is the only enforcement point. The overseer-side computation is a pre-check. (BINDING.)

- Nothing on the overseer side is a security control for this threshold. In particular:
  - No agent-side check may be cited as the reason a PR is safe to approve above the ceiling.
  - `T_shared` refusal on the overseer side is a courtesy that prevents the red-gate round trip.
- This is why AF-6 scorer drift is a residual, not a defect. Drift can cause disagreement in either direction. Both directions resolve conservatively: a red gate, or a refusal followed by a human.

### AD-9: `overseer.md` names the procedure. (BINDING. REQ-1(c). Lands in S5.)

- Approve-eligibility condition 2 (`:587`) becomes: "The **ceiling tier** — `max(T_shared from bash bootstrap/pr_review.sh compute-tier, your assessment tier)` — does not exceed `OVERSEER_CEILING`".
- The merge-authority matrix input (`decide_merge_authority(risk_tier=…)`) is that same ceiling tier.
- The assessment tier procedure:
  - run **the main clone's** `scripts/oversight/run_validators.sh` with cwd set to a PR-head worktree under `$TMPDIR`;
  - pass **explicit** file paths taken from `compute-tier`'s `files_scored` plus the non-`.py` PR files, never `--diff` (VF-5);
  - apply `tier_floor`;
  - pass `--assessment-summary` (S4).
- Update `:466` (refusal reasons), `:467` (the bypass now also fires on the claim) and `:473` ("wait for the tier-ceiling check" stays; add "a `compute-tier` result above the ceiling means `comment`, never approve-then-dismiss").
- A static test pins the `compute-tier` reference and the phrase "ceiling tier" in condition 2.

---

## 3. Threat model and failure modes

**Trust boundaries.**
- These are untrusted: PR head content, the files-API `patch` text, review bodies (except their GitHub-attributed author and `commit_id`), and every agent-supplied argv value.
- These are trusted: the base checkout in CI; the overseer's main clone, for liveness only (AD-8).

| Threat or failure | Control | Status |
|---|---|---|
| A PR edits `rn_calculator.py` to score 0 | CI runs base-checkout code; the PR's copy is never executed (AD-2) | Closed (REQ-5 AC) |
| A PR edits `require_tier_ceiling.py` or `tier_scope.py` | The same, plus `scripts/framework/**` is protected | Closed |
| An unprotected scorer dependency (`rn_calculator.py`) is weakened by a merged PR, and becomes the base | The protected-surface list does not cover it today | **Open**: ARCH-ESC-1 |
| An overseer `--tier` lower than the enforced tier → APPROVED, then a red gate (#1907) | `submit-verdict` computes `T_shared` itself (AD-4) | Closed in S1 |
| The overseer withholds above the ceiling, the gate computes below it, and the bypass deadlocks (VF-7) | Upward claim in the bypass (AD-6) | Closed in S2 (pending ESC-3 / ARCH-ESC-2) |
| A forged or quoted claim lowers the tier | `max`; attribution; one marker on the final line; malformed → CRITICAL (AD-6) | Closed (can only raise) |
| A stale claim from an older head | `head` must equal `commit_id` and H1 | Closed |
| Head pushed mid-computation (AF-1) | H1/H2 double read; pinned fetches | Closed in S1 |
| An unparseable changed file is silently dropped (AF-2) | `--strict-parse` → exit 2 | Closed in S1 |
| A not-found error for a non-deleted file is skipped (AF-3) | Skip only on `status: removed` | Closed in S1 |
| A truncated file list | The 3000 cap → exit 2 | Closed in S1 |
| A truncated or malformed patch discounts a change | Whole-file fallback for that file (AD-5) | Closed in S3 (raises only) |
| A change sits next to a hot function and inherits its RN through context lines | Context lines contribute nothing (AD-5) | Closed in S3 |
| A one-line edit inside a hot function is discounted | The whole function is scored at head (AD-5, REQ-7) | Closed in S3 |
| A stale or foreign `summary.json` (VF-8) | Removed from the ceiling path (S1); `A` bound by head and file set (S4) | Closed |
| The overseer's composite is gamed by running PR-head validator code | Upward-only, so it cannot go below `T_shared`; S4 refuses a non-base validator commit | Reduced. Composite-only dimensions stay overseer-asserted (R-1) |

**Residuals.**
- **R-1.** Risk from the dimensions only the composite sees (`static_analysis`, `migration_risk`, `ip_check` and the rest) is enforced only through the overseer's honest assessment. Today's gate does not enforce it either, so this is **not a regression**. #1427 tracks the wider worker-tier question.
- **R-2.** Scorer drift between CI's event `base.sha` and the overseer's `main` (AF-6) can cause a single disagreement. Both directions are conservative, and the AD-7 digest makes the drift visible.
- **R-3.** CI's interpreter is `ubuntu-latest`'s `python3`, and the overseer's may differ. AST-derived RN is stable across 3.10 to 3.13 for source both can parse. Syntax that only one of them can parse fails closed on that side. Pinning `actions/setup-python` would add a dependency (NFR-1) and is not done.

---

## 4. Slices (each ≤ 15 files including tests, ≤ 10 commits, independently mergeable)

| # | Slice | Files (approx.) | Tier | Protected surfaces touched | Depends on | Merge waits on |
|---|---|---|---|---|---|---|
| **S1** | Pinned, fail-closed `T_shared` (whole-file mode, so today's semantics); `compute-tier`; `submit-verdict` G1 on `max(T_shared, --tier)` (AD-1, AD-3, AD-4, AD-7 core) | `scripts/framework/require_tier_ceiling.py`; `scripts/framework/tier_scope.py` (new; claim and scope stubs absent, `TierResult` helpers only); `scripts/oversight/validators/rn_calculator.py` (`--strict-parse`); `scripts/automation/pr_review_cli.py`; `tests/framework/test_require_tier_ceiling.py` (named edits only, AR-9); `tests/framework/test_tier_result_inputs.py` (new: AF-1 to AF-4, file cap, REQ-6 AC, REQ-11 AC(a)); `tests/oversight/test_rn_calculator_strict_parse.py` (new); `tests/automation/test_pr_review_enforced_tier.py` (new: REQ-2 AC(a), REQ-3 AC, `enforced_tier_unavailable`, W4/W8-W14 untouched); `tests/framework/fixtures/tier_1909/` (≤ 2 files); `DECISIONS.md`; `SCRIPTS-INDEX.md`: **≈ 12** | **HIGH** → HUMAN_REQUIRED. `security-reviewer` mandatory; second review HIGH+ | `scripts/framework/**` (`:28`). `bootstrap/**` only if TD finds `pr_review.sh` needs an edit (AD-4) | — | Human CODEOWNER approval, and ARCH-ESC-3 (default accepted by approving the PR) |
| **S2** | Upward-only claim; `ceiling_tier`; gate approve case and #1426 bypass on `T`; generated verdict block; reviewer trigger on the effective tier (AD-6, AD-7) | `scripts/framework/tier_scope.py`; `scripts/framework/require_tier_ceiling.py`; `scripts/framework/require_overseer_approval.py`; `scripts/automation/pr_review_cli.py`; `tests/framework/test_tier_claims.py` (new: forgery, quoted marker, stale head, malformed → CRITICAL, lower claim never lowers); `tests/framework/test_require_overseer_approval.py` (adds the VF-7 fixture: REQ-2 AC(b), REQ-1 AC(b)); `tests/automation/test_pr_review_enforced_tier.py`; `DECISIONS.md`; `SCRIPTS-INDEX.md`: **≈ 9** | **HIGH** → HUMAN_REQUIRED. `security-reviewer` mandatory; second review HIGH+ | `scripts/framework/**` | S1 | ESC-3 and ARCH-ESC-2 rulings; human CODEOWNER approval |
| **S3** | Function scoping of the RN term (AD-5) | `scripts/oversight/validators/rn_calculator.py` (`--line-scope`, spans); `scripts/framework/tier_scope.py` (`touched_new_lines`); `scripts/framework/require_tier_ceiling.py`; `tests/framework/test_tier_scope_patch.py` (new: parser and `audit_predicate` parity); `tests/oversight/test_rn_calculator_line_scope.py` (new: decorators, nesting, deletion-only hunks); `tests/framework/test_require_tier_ceiling.py` (named whole-file → scoped edits); `tests/framework/fixtures/tier_1909/` (the #1907 shape: REQ-1 AC(a), REQ-7 ACs, REQ-8 AC, REQ-10 AC); `DECISIONS.md`: **≈ 9** | **HIGH** → HUMAN_REQUIRED. `security-reviewer` mandatory; second review HIGH+ | `scripts/framework/**`; also `rn_calculator.py` if ARCH-ESC-1 = (a) lands first | S1 (S2 recommended first; see Order) | **ESC-1 and ESC-2** rulings; human CODEOWNER approval |
| **S4** | Bind the overseer's assessment: `run_validators.sh` stamps `head_sha`, `files` and `validators_commit` into `summary.json`; `submit-verdict --assessment-summary` applies `max(tier, tier_floor)`, refuses on a head or file-set mismatch, and refuses a validator commit not reachable from `origin/<base>` (REQ-11 AC(b), REQ-5 overseer side, VF-5) | `scripts/oversight/run_validators.sh` (one aggregation hunk); `scripts/framework/tier_scope.py` (`assessment_tier`); `scripts/automation/pr_review_cli.py`; `tests/oversight/test_run_validators_summary_binding.py` (new); `tests/automation/test_pr_review_assessment_summary.py` (new); `DECISIONS.md`: **≈ 6** | **MEDIUM** → HUMAN_REQUIRED | `scripts/oversight/run_validators.sh` (`:30`), `scripts/framework/**` | S2 | Human CODEOWNER approval |
| **S5** | `overseer.md` procedure (AD-9) and its static pin | `.claude/agents/overseer.md`; `tests/framework/test_overseer_tier_procedure.py` (new); `DECISIONS.md`: **3** | LOW → HUMAN_REQUIRED. Authored by the top-level session (CLAUDE.md, #1347) | `.claude/agents/**` (`:16`) | S2, S4 (S3 if ruled) | Human CODEOWNER approval |

**Order.**
- S1 can be designed and built now.
- S2 follows S1, once ESC-3 and ARCH-ESC-2 are ruled.
- **S3 must not merge before S2.** S3 lowers `T_shared` for inherited risk. Without S2's claim, more PRs would fall into the VF-7 deadlock: the overseer withholds on a whole-file composite or promotion while the scoped gate computes below the ceiling.
- S4 follows S2. S5 is last.

**Not touched by any slice:**
- `.github/workflows/**`, including `require-tier-ceiling.yml`, whose entry point and arguments are unchanged;
- `scripts/framework/protected_surfaces.txt` (unless ARCH-ESC-1 = (a), which is then its own one-line human-authored PR);
- `scripts/oversight/validators/schema.py`, `WEIGHTS` and the thresholds;
- `merge_authority.py`;
- `scripts/automation/lib/github.py`;
- `audit_predicate.py`, which is read for parity only.

### Test obligations (all hermetic: a stubbed `gh` on PATH returning fixture JSON, temp dirs inside the conftest budget)

- **S1:**
  - Every AD-3 fail-closed path → exit 2, or a refusal with no POST.
  - The #973 test passes unchanged (REQ-4 AC(b)).
  - REQ-6 AC: a behind-base fixture, where the stubbed files API omits the base-only file, gives the same tier as the same PR rebased.
  - `compute-tier` output equals `require_tier_ceiling.main()`'s tier for the same stub (REQ-3 AC).
- **S2:**
  - A claim lower than `T_shared` gives `T_shared`.
  - A claim higher than the ceiling with a human approval makes the bypass return 0 (REQ-2 AC(b)).
  - A claim from a non-overseer login is ignored.
  - Two markers → CRITICAL.
  - A claim for an older head is ignored.
- **S3:**
  - The #1907 fixture is not CRITICAL from RN, and stdout names the RN-32 function as out of scope.
  - A one-line change inside the RN-32 function → CRITICAL.
  - A new function with RN ≥ 15.6 → CRITICAL.
  - A deletion-only hunk inside a function puts that function in scope.
  - A decorator-only change puts the function in scope.
  - A renamed file is scored whole-file.
  - An absent patch is scored whole-file, with a fallback line printed.
  - REQ-9 AC: one test each for the RN term winning, the structural term winning, and (with S2) the assessment winning.

---

## 5. Requirement amendments (recorded here; TD applies them as overriding)

- **AR-1 (REQ-1).** "The same tier value" is defined as `T = ceiling_tier(T_shared, A)`. All three consumers evaluate it through one function, over the same pinned head and the same claim. `T_shared` alone is what CI recomputes, and `A` is read from the overseer's review.
- **AR-2 (REQ-9; ESC-1 B).** The composite-with-floors term reaches `T` through `A`, which the overseer computes with trusted main-clone code and S4's floor and head binding. CI does not recompute it (AF-5). CI's independent term is `max(RN_in_scope, structural)`.
- **AR-3 (REQ-5).** The rule becomes: "No agent-produced value may **lower** the ceiling tier. An agent-produced value may **raise** it only when it is authored by the GitHub-attributed overseer identity and bound to the current head SHA." `T_shared` is always computed from trusted base code. This is pending ESC-3 and ARCH-ESC-2.
- **AR-4 (REQ-6).** "The set `gh pr diff --name-only` reports" is operationalised as the paginated `pulls/{n}/files` listing for a pinned head. Reaching the listing cap fails closed.
- **AR-5 (REQ-4).** Allowed fallbacks are exactly AD-5's whole-file cases. Everything else that cannot be obtained is exit 2 or a refusal. Also allowed is an approval with no claim, which falls back to `T_shared` and prints a warning (AD-6).
- **AR-6 (REQ-8).** The scope unit is the function span, from decorators to `end_lineno`. Touched lines are `+` lines and both sides of each deletion point; context lines do not count. The module-level clause has no effect on the RN term.
- **AR-7 (REQ-11).** Satisfied in two steps. S1 removes every summary read from the ceiling path. S4 binds the overseer's summary by head SHA, file set and validator commit, and applies `tier_floor`.
- **AR-8 (REQ-3).** The mechanism is `pr_review.sh compute-tier`, plus `submit-verdict`'s own recomputation. Both call `compute_tier_result`.
- **AR-9 (REQ-12).** Expected named test edits in `test_require_tier_ceiling.py`:
  - S1 removes `test_try_validator_summary_reads_tier` and `test_compute_tier_prefers_summary` (REQ-11);
  - S1 inverts `test_fetch_head_python_skips_escaping_paths` (AF-4: now exit 2);
  - S1 changes `test_fetch_head_python_skips_deleted` to key on `status` (AF-3);
  - S1 updates the `get_changed_files` stubs for the files-API shape;
  - S3 adds scoped variants.

  Each of these is named in its PR body. `test_critical_python_pr_caught_above_high_ceiling` is not modified.

I endorse REQ-2, REQ-7, REQ-10, NFR-1 to NFR-4 and §3 (out of scope) as written.

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **Routed to the human. These are not mine to sanction:**
  - **Inherited risk stops raising the tier** (ESC-1, ESC-2; S3). This is user-visible: some PRs that are HUMAN_REQUIRED today become auto-mergeable.
  - **The overseer's attributed claim can trigger the #1426 bypass** (ARCH-ESC-2; S2). This changes which approvals satisfy a required check.
  - **Composite-only risk stays overseer-asserted at the gate** (ESC-3; R-1).
  - **An interim behaviour change after S1** (ARCH-ESC-3). Hot-file PRs become HUMAN_REQUIRED, where today they get a red gate and a dismiss-and-repost.
  - **A larger protected surface** (ARCH-ESC-1). This adds operational burden: more human-gated PRs.
- **No cost, topology or retention change.** There is no new service, credential or workflow. The gate adds two `gh` calls (the second head read, and the compare call for `merge_base`) and one paginated files call in place of `gh pr diff`.
- **Startup gap: yes.**
  - ADR-1657 and TD-1657 (`:168`) built G1 on the premise that "the overseer always holds the computed tier", without defining which computation.
  - #1426 built the bypass on the gate's tier alone, without asking whether the overseer withholds for the same reason.
  - "What is the tier" should have been settled before either control was designed against it.
  - **Recommendation to the worker:** open or annotate a `startup-artifact-gap` issue cross-referencing #1657, #1426 and #1909. I have not filed it, per this task's instructions.
- **Affected sign-offs:**
  - **TD-1657 G1 and the wrapper W-tests.** The G1 logic is extended (AD-4) and its sign-off must be **re-reviewed in S1** against this ADR. W4 and W8-W14 must pass unmodified (REQ-12), and `above_ceiling_approve` is kept for the caller-tier case.
  - **ADR-1657 AD-3 (trigger scoping).** It stands. S2 feeds the trigger the enforced tier and adds no term. The S2 reviewer confirms that no trigger condition was added.
  - **#1426 bypass.** Its semantics are extended (AD-6). **Re-review in S2.** Until S2 merges, the bypass behaves as today.
  - **#973.** It stands. Its regression test is unmodified, and S1 strengthens the fail-closed paths (AF-1 to AF-4).
  - **#1299 / #972 (workflow trigger and checkout).** They stand. The workflow is untouched.

---

## 7. Open human escalations

| ESC | Architect | Resolved by architecture? | How the design changes if ruled differently | Gates |
|---|---|---|---|---|
| **ESC-1** (what the ceiling gate is for) | **Concur: (B).** CI keeps an independent RN term that the overseer cannot dilute, and agreement comes from construction, not from loosening. | **No.** It sets what the CORE threshold measures | **(A)** composite only: drop the RN term from `T_shared`, so CI's independent floor becomes `structural` only; S3 is not built; everything else stands. *Not recommended*: a genuine RN-32 addition could auto-merge on an under-reported `A`. **(C)** whole-file plus option 3: S3 is not built (`RN_SCOPE = "file"`), and S1 and S2 stand. S2's claim still fixes VF-7, which (C) alone does not. | S3 merge |
| **ESC-2** (exclude inherited risk) | **Concur: function unit** (AD-5). The 2026-10-03 ruling concerns gate *violations*. The tier measures *this change*, and a function the PR touches is scored in full, so nothing the PR changes is discounted. | **No.** The human must say whether the ruling extends to the tier | **(b) line-level:** refused. It contradicts settled REQ-7 and would need REQ-7 re-ruled first. **(c) no exclusion:** identical to ESC-1 (C), so S3 is not built. | S3 merge |
| **ESC-3** (dimensions CI cannot reproduce) | **Propose (d), a new option:** they enter only through the overseer's attributed, head-bound, upward-only claim (AD-6). This takes (c)'s agreement without its downward trust. | **No.** It amends REQ-5 (AR-3) | **(a) exclude on both sides:** remove `A` from `T`. The overseer's ceiling decision then ignores composite-only risk, which is **looser than today's overseer** and is not recommended. VF-7 for the JS and promotion cases reopens unless ARCH-ESC-2 is kept. **(b) provision in CI:** S2 stands. A later slice adds the reproducible dimensions to `T_shared`, renormalised over a **fixed** set that fails closed if a member errors (AF-5). That needs a workflow edit (`.github/workflows/**`) and an NFR-1 waiver. **(c) as written:** rejected, because it trusts a downward value. | S2 merge |

**ARCH-ESC-1 (tier `safe-default`; product-boundary: operational burden).** Should the ceiling scorer's code outside `scripts/framework/**` become a protected surface?
- Today `rn_calculator.py` is unprotected. A PR that weakens it merges under overseer authority, and from the next event it **is** the trusted base that CI runs.
- **(a) Recommended.** Add `scripts/oversight/validators/rn_calculator.py` to `protected_surfaces.txt`, as a human-authored one-line PR, regenerating CODEOWNERS. Every future change to it then needs a human.
- **(b)** Leave it as it is, and accept that the gate's trusted base can be lowered by an overseer-merged PR (a #1427-class exposure).
- Under (a), S1 and S3 also count `rn_calculator.py` as protected. Nothing else changes.

**ARCH-ESC-2 (tier `hard-tradeoff`; product-boundary: who may satisfy a required check).** May the overseer's attributed, head-bound claim make the #1426 bypass fire?
- **(a) Recommended: yes** (AD-6). VF-7 closes in every case: JS-lane, composite-driven and promotion. The overseer gains no power to merge. It gains only the power to say "this needs a human, not me", which it already has by withholding approval. Today that withholding deadlocks, and the claim removes the deadlock.
- **(b) No.** VF-7 stays open wherever `A > T_shared`. Those PRs need an admin override, or ESC-3 (b).
- Under (b), S2 keeps the claim **for the gate's approve case only** (an informational upward check), and the bypass stays on `T_shared`.

**ARCH-ESC-3 (tier `safe-default`; user-visible interim behaviour).** May S1 merge before ESC-1 and ESC-2 are ruled?
- **Recommended: yes.** After S1, a PR touching a hot file is refused `approve` before posting, gets `comment`, and goes HUMAN_REQUIRED. Today it gets APPROVED, a red gate, a dismissal and then `comment`. The end state is the same, with no red check and no wasted cycle. Nothing becomes looser.
- S1 touches `scripts/framework/**`, so the human CODEOWNER approval of the S1 PR is where this default is accepted or refused.

```yaml
adr: ADR-1909
issue: 1909
verdict: APPROVED_WITH_AMENDMENTS
single_source_of_truth: "scripts/framework/require_tier_ceiling.py: compute_tier_result / compute_tier_for_pr (+ ceiling_tier in S2); pure helpers in scripts/framework/tier_scope.py"
ceiling_tier: "T = max(T_shared [trusted base code, pinned head, PR content as data], A [overseer's attributed head-bound claim, upward only])"
codable_now: [S1]
design_now_merge_after:
  S2: [S1, ESC-3, ARCH-ESC-2]
  S3: [S1, S2, ESC-1, ESC-2]
  S4: [S2]
  S5: [S2, S4]
protected_slices: {S1: ["scripts/framework/**"], S2: ["scripts/framework/**"], S3: ["scripts/framework/**", "rn_calculator.py if ARCH-ESC-1=a"], S4: ["scripts/oversight/run_validators.sh", "scripts/framework/**"], S5: [".claude/agents/**"]}
risk: {build: HIGH, S1: HIGH, S2: HIGH, S3: HIGH, S4: "MEDIUM, HUMAN_REQUIRED", S5: "LOW, HUMAN_REQUIRED"}
mandatory_reviewers: {S1: [code-reviewer, security-reviewer], S2: [code-reviewer, security-reviewer], S3: [code-reviewer, security-reviewer], S4: [code-reviewer, security-reviewer]}
hard_constraints_not_waivable:
  - "AD-2 ceiling-tier code from trusted base; PR content parsed, never executed; workflow untouched"
  - "AD-3 every new input fails closed; fallbacks only raise; no summary.json on the ceiling path"
  - "AD-6 agent-supplied tier information only raises T, via max in ceiling_tier only"
  - "AD-8 CI is the only enforcement point"
not_touched: [".github/workflows/**", scripts/oversight/validators/schema.py, scripts/automation/lib/merge_authority.py, scripts/automation/lib/github.py, scripts/framework/audit_predicate.py]
escalations:
  - {id: ESC-1, tier: hard-tradeoff, recommended: B, gates: [S3]}
  - {id: ESC-2, tier: hard-tradeoff, recommended: function-unit, gates: [S3]}
  - {id: ESC-3, tier: hard-tradeoff, recommended: "d (upward-only attributed claim)", gates: [S2]}
  - {id: ARCH-ESC-1, tier: safe-default, recommended: "a (protect rn_calculator.py)", gates: []}
  - {id: ARCH-ESC-2, tier: hard-tradeoff, recommended: "a (claim may fire #1426 bypass)", gates: [S2]}
  - {id: ARCH-ESC-3, tier: safe-default, recommended: "S1 merges before ESC-1/2", gates: [S1]}
```

---

## 8. Notes and follow-ups (named, not filed here)

- **FU-1.** A `startup-artifact-gap` issue for #1657 and #1426 (§6).
- **FU-2.** `docs/FABERIX-ROLES.md` §5 describes the bypass condition. It is protected and should gain the claim clause after S2. It needs a human-authored edit.
- **FU-3.** The requirements' recommendation to refactor `test_pipeline_subshell_shows_nested_argv_child_benign_1265` stays optional. After S1 it costs a human approval per hot-file PR, not a red gate.
- **FU-4.** #1427: the worker-side tier. AD-6's upward-only rule is the pattern to reuse there.

## Escalation flag (CORE self-flag)

RISK: HIGH. This changes the computation behind a CORE threshold and the semantics of two required checks. A scoping bug in S3 could admit a PR whose diff is genuinely above the ceiling. That is why S3 is gated on S2 and on two human rulings, and why every fallback raises the tier.

CONFIDENCE:
- **HIGH** on §0. Every citation was read in this session at `8eb122060`, and VF-2 was re-run.
- **HIGH** that `max` with attribution and head binding cannot lower `T`.
- **MEDIUM** on two points TD must confirm: that the GitHub files API `patch` field is present for every non-binary, non-oversize file (AD-5 falls back upward if not), and that `pr_review.sh` passes `compute-tier` through unedited (AD-4).

BLAST RADIUS:
- every overseer approval and every merge through `require-tier-ceiling` and `require-overseer-approval`;
- consumer projects on install, because these are shipped `scripts/framework/**` files.

Change classification: STRUCTURAL.

## Human Review Required

- **ESC-1 and ESC-2** must be ruled before S3 merges.
- **ESC-3 and ARCH-ESC-2** must be ruled before S2 merges.
- **ARCH-ESC-1** is a one-line protected-surface addition, if accepted.
- **ARCH-ESC-3** is accepted or refused by approving the S1 PR.
- Every slice touches a protected surface and needs a human CODEOWNER approval.
- S1 may be designed and built now.
