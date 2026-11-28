# TD-2357-S1b — Overseer second review: cron phase, G1c approval gate, marker

| Field | Value |
|---|---|
| Issue | #2357 (slice S1b; S1a merged as PR #2384) |
| ADR | `docs/v0.7.0/ADR-2357-overseer-second-review.md` (AD-1 … AD-12) |
| Predecessor TD | `docs/v0.7.0/TD-2357-S1a-overseer-second-review-runner.md` (§5.6, §5.8, §5.9, §7, §10) |
| Binding human ruling | ScottThurlow, 2026-11-17: the 146 field-drop mutant survivors from the S1a run are disposed in this TD. Each field gets a test that reads it through a real S1b reader (cron phase, G1c, or marker). The S1b PR carries a scoped mutation run showing those mutants killed. |
| Status | **APPROVED_WITH_CHANGES by architect, 2026-11-18, design-loop iteration 1 of 5.** Architect amendments AR1-AR16 are applied in place and listed in §0.1. Q0, Q3 and Q4 are ruled by the architect. Q1 is resolved within the human ruling, with option C. Q2 needs a human answer before the S1b PR is submitted (see Q2). |
| Change classification | **additive** for S1a code (new result keys, stricter `load_record`). The S1b/S1c split is the contingency ADR AD-11 already pre-authorized, so it is **not** a new structural decision (architect, Q0). |

```
RISK: HIGH
CONFIDENCE: MEDIUM
BLAST RADIUS: overseer cron cycle (every actionable PR), the overseer approve path
  (pr_review_cli submit-verdict G1c), the second-review record reader (stricter integrity
  → records that were valid under S1a may now read as absent → re-review, never approval)
```

## Human Review Required

- **Q2 (open, human):** Whether the mutants in §11.5 may be left as `equivalent`, against the 2026-11-17 ruling that the S1b PR show the 146 mutants killed. The architect's corrected list has 27 candidates (AR22). See Q2 and §11.5. Coding may proceed. The S1b PR is not submitted until the human answers.
- **Same-uid record-forgery residual (AR25), for the CODEOWNER at merge.** Until slice S1d lands, the overseer model's own Bash or Write tool can create a record that G1c accepts. The sandbox does not deny writes to `records/`. The only barrier is the `overseer.md` prohibition. This is still strictly stronger than main, which has no G1c. Merging S1b accepts that residual until S1d. S2 is `blocked_by` S1d and by the AR26 follow-up. *(Q2 was answered by the human on 2026-11-20: A, with a mutation score ≥75% per module as the bar.)*
- Ruled by the architect, no human answer needed: **Q0 = A** (S1b/S1c split, pre-authorized by AD-11); **Q3 = A** (`untrusted-checkout` counts as a strike); **Q4 = A** (`second_review_record_unverifiable`). **Q1 = C** satisfies the human ruling. Q1-A would deviate from it.

---

## Open questions (autonomous cycle: answer A/B/C; work proceeds on the recommendation)

**Q0. Slice shape. RULED A by the architect (2026-11-18).** ADR AD-11's "Contingency for S1b" pre-authorizes this split: route head-carry and the bounce marker move to S1c (`merge_authority_cli.py`, `lib/merge_authority.py`, `test_merge_authority_cli.py`), S1c lands before S2, and S1b carries the `review_worktree.sh --expect-sha` interim prose. The only addition here is S1c's prompt artifact, which is incidental. This is an ADR-authorized path, not a new structural decision, so it needs no human. The single-PR file count is 18 (§2.1). The ≤15-file PR limit applies.
- **A (ruled):** Take the S1c contingency already written in AD-11. S1b has 15 files. S1c has `merge_authority_cli.py`, `merge_authority.py`, `test_merge_authority_cli.py` and the `merge_authority` prompt artifact. S1b ships the interim route prose from AD-11 (§9.3). S1c must merge before S2.
- **B:** One 18-file PR under a recorded file-limit waiver.
- **C:** Drop the TD, ADR correction note and prompt artifact from S1b to reach 15 files. Rejected: the prompt artifact is required by `ip_check`/`prompt_audit` at MEDIUM+, and the TD is the coder's contract.

**Q1. The 21 mutants the draft called route-only** (`_default_run_cmd_7/14/21`, `_Ctx.run_4`, `_changed_paths_12/13/15/16`, `_path_of_10..15`, `_fp8_4`, `build_entries_13/14/16/67`, `_vendor_status_69/73`). **RESOLVED: C, within the human ruling (architect, 2026-11-18).**
- *Architect correction.* Eight of the 21 do not touch finding content. `_default_run_cmd_7/14/21`, `_Ctx.run_4`, and `_changed_paths_13/16` drop or replace `env`, and `_changed_paths_12/15` drop the git timeout. The T-INT real-`run_cmd` harness (§11.3) kills those, because its stub `git` records env and timeout. The other 13 are finding content: path, fingerprint, sort rank, overflow count and verdict detail.
- *Against the ruling.* The 2026-11-17 ruling says each field gets a test that reads it **in S1b**, and **the S1b PR** shows them killed. **A deviates from that**, because it moves the kill to S1c's PR, so A would need a human answer. C complies, so it needs none.
- **C (adopted):** S1b tests read the findings file the runner wrote. They assert exact `path`, `slug` (fp8), order and `sr-overflow` count, and `detail`. They also pass the file, with `reviewed_head` popped, through `merge_authority.canonicalize_findings_ex`. That is the parser route calls, and AD-6 test 1 already uses it. `lib/merge_authority.py` is **not** added to mutmut `source_paths`. It is only imported, so it goes in mutmut's `also_copy` if the scratch tree needs it. All 21 are in the S1b kill bucket.
- **A (not adopted; would need a human):** S1c's PR carries the kills.
- **B (not adopted):** file-limit waiver, pulling route into S1b.

**Q2. Equivalent-mutant dispositions (27 candidates after the architect's corrections, §11.5). OPEN: needs a human answer.** The ruling says the S1b PR shows "those mutants killed", and an equivalent mutant cannot be killed. Leaving any of the 146 as `equivalent` departs from the literal ruling, under every option below, so the architect does not decide it. Coding proceeds, because the killing tests are needed either way. The S1b PR is not submitted until the human answers. The worker asks with `escalate_to_human.sh`.
- *Architect correction to the draft.* The draft listed 36 mutants but named only 35. One of them, `_main_20`, is not in the 146 at all: it is an argparse `prog` text mutant. Most of the one-line proofs described a different mutation from the one in `osr-class6.tsv`. Six named mutants are killable and move to the kill bucket. `write_raise_44` is one of them: it passes `pr=None` to `_raise_valid`, so an existing raise is never seen and a later lower `write_raise` **lowers** the tier. That is a safety property, not an equivalence. The corrected table is §11.5.
- **A (recommended to the human):** Accept the 27 corrected proofs in §11.5. The mutation-run comment lists each as `equivalent` with its proof checked against the actual mutated line.
- **B:** Require a killing test for each anyway. The coder reports `unkillable` for each it cannot kill, and those go back to the human.
- **C:** As A, minus any the fresh run reports killed.

**Q3. `untrusted-checkout` strike policy. RULED A by the architect (2026-11-18).** AD-1 says the phase must not run the runner from an untrusted checkout. AD-12 says "strike counter outside `records/`, or hold on first". The phase's strike directory is outside `records/` (§4), so counting satisfies AD-12. An off-main overseer clone is usually transient: the clone is mid-sync, or the main-diverged guard fired. Holding on the first strike would label every open PR for a condition the next cycle usually clears. Counting to 3 still bounds it under the "pending is bounded" rule. The runner's own `untrusted-checkout` pending, which is a race with the phase check, counts as a phase strike too (§6.6).
- **A (ruled):** Count it as a strike, so it holds at 3. It is usually transient: the cron sync may be mid-fast-forward, or the main-diverged guard fires the same cycle. Three cycles is about 90 minutes at the default cadence.
- **B:** Hold on the first occurrence. Every PR gets `needs-human` the first time the overseer clone is off main, which is noisy, and a label must then be cleared by hand on every PR.
- **C:** Neither: emit `pending untrusted-checkout` uncounted. Rejected, because it is unbounded and violates "pending is bounded by pending-stuck".

**Q4. Fourth G1c refusal reason. RULED A by the architect (2026-11-18).** AD-9 defines `second_review_record_missing`, `second_review_not_approved` and `second_review_tier_raise`. A `head_lock` timeout or IO error while reading the record is none of these. The new reason is still a refusal (exit 3), so it fails closed and changes no decision. It only tells the model why. The model treats it like `record_missing`: do not approve, change no label, re-evaluate next cycle. It is bounded because the cron phase finishes before the model runs, so a cron cycle never contends for the lock. The ADR correction note adds the row to AD-9's table.
- **A (ruled):** Add `second_review_record_unverifiable` (exit 3, refusal). Folding it into `record_missing` would tell the model to wait for a review that already exists.
- **B:** Map it to `second_review_record_missing`.

---

## 0. Corrections and extensions to the ADR / S1a TD

| # | Source | Correction / extension | Why |
|---|---|---|---|
| C1 | AD-11 | S1b is split. S1c takes route head-carry (AD-10) and the `bounced=true` marker. S1b renders `bounced=false` always. | File count is 18 > 15 (§2.1). |
| C2 | AD-3 | The OSR line gains `persisted=`, `count=`, `last_reason=` and `label=`. `vendors=-` whenever `tier=-`. | AD-3's correction note already allows `record: null`. The model needs `persisted` to know whether `mark-hold-label` exit 3 is expected, and `count` to see how close a PR is to pending-stuck. `label` gates the HUMAN_REQUIRED comment. |
| C3 | TD-S1a §5.8 | Two result keys are added: `pending_count` (int\|null) and `pending_last_reason` (token\|null). `RESULT_KEYS` is exported as a module constant. | Before this, the phase could not report the pending count without reading the counter file directly. P6-style single-reader rule: the runner alone reads its counter. |
| C4 | TD-S1a §7 | `load_record` enforces record integrity (owner + mode) and record self-consistency (§7). A failing record reads as absent. | AD-9 says integrity is binding. ADR left the mechanism to TD. |
| C5 | TD-S1a `sanitize` | GitHub mention and link neutralization is added (§5.4). | The marker and OSR line are rendered into a model prompt and a GitHub comment. Codex item 7 (ADR). |
| C6 | AD-9 | Reason `second_review_record_unverifiable` is added (Q4). | §8.3. |
| C7 | AD-9 | `--tier SAFE` maps to LOW for tier comparison. | `_VALID_TIERS` in `pr_review_cli` includes SAFE. The runner's `TIERS` does not. |
| C8 | AD-12 | Helper `bin/lib/osr_phase.py` owns budget accounting, strike state and line rendering. Bash owns process control only. | `set -euo pipefail` bash with jq parsing of untrusted runner stdout is the failure surface the ADR's fail-closed rule is about. Precedent: `bin/lib/usage_pause.py`. |

### 0.1 Architect amendments (iteration 1, 2026-11-18, binding; AR23-AR27 added 2026-11-21 on review of the built code at `0038e5521`)

Each item was checked against the code at `aebc96aab`. Each is applied in place in the section named.

| # | Defect in the draft | Amendment | § |
|---|---|---|---|
| AR1 | **Binding item 2 was not met.** The draft said the runner already counts `lock-busy`, `state-write-failed`, `config-error` and `github-error`. It does not: all four are in `PENDING_UNCOUNTED` (`overseer_second_review.py:98-109`). `lock-busy` and `state-write-failed` are returned by plain `_result(...)` (`:1487`, `:1492`), so they bypass `_pend`. The draft's phase did not count them either, so they were unbounded. | The phase strikes `lock-busy`, `state-write-failed`, `config-error`, `github-error` and `untrusted-checkout` from the runner. It also strikes a counted reason whose `pending_count` is null, which happens when the runner's counter was skipped. | §6.5, §6.6 |
| AR2 | `mark-hold-label --pr N` is an invalid call. The CLI requires `--head <sha40>` and `--applied true\|false` (`:1560-1562`), so the draft's call always exits 2. | Call `mark-hold-label --pr N --head <line head> --applied true`. | §6.4 |
| AR3 | The draft's ingest rejected the runner's `verdict=skipped-held reason=held-label` (`:1460`). The phase skips held PRs only when the pre-filter saw the label. A detail-fetch fallback (`bin/hos-cron:1601-1602`) or a label added after the pre-filter reaches the runner, and its correct answer would then have become an `invalid-line` strike. | Accept `skipped-held`/`held-label` from the runner: no action and no strike. A reused hold returned on a held PR renders `label=existing`. | §5.3 |
| AR4 | §5.3 mis-stated the result shape. `record` is an absolute path string, not a dict, and it is set on every final and persisted hold. `vendors` is a VENDORSETS string, not a list. The runs dir is under `$REPO_ROOT/.claudetmp/...`, not `_HOS_DIR`. | §5.3 items 4, 6 and 7 are corrected, and `--runs-dir` is added to the `ingest` signature. | §3.2, §5.3 |
| AR5 | **Binding: the non-persisted hold is rendered with count and last_reason.** The draft made `pending_count` null on every hold, so the `pending-stuck` hold, persisted or not, rendered `count=-`. | `pending_count` and `pending_last_reason` are non-null whenever this call advanced the runner's counter. That covers a counted pending and a `pending-stuck` hold with `reused=false`. | §3.1, §5.2, §5.3 |
| AR6 | The budget rule departed from AD-12. The draft replaced `--cache-only` with "do not call the runner", so a PR that already had an approve record was not approvable that cycle. Its `--elapsed` rule with the budget floored at one per-PR max could also refuse the first PR (elapsed > 0), which leaves no progress guarantee. `SPENT=0\|1` contradicted "add SPENT's seconds". | AD-12 as written: `RUN` when no uncached review has run this cycle or `elapsed + per_pr <= budget`, else `CACHE_ONLY`, which calls the runner with `--cache-only`. A `pending budget` result records the PR as deferred, so it runs first next cycle. `ingest` reports `UNCACHED=0\|1`. | §3.2, §6.3 |
| AR7 | **AD-1 says the phase never aborts the cycle.** The draft accepted that a `set -e` abort ends the cycle with no model run. That would stop merges on human approval and every other overseer duty. | The phase runs in a subshell with `set -e` restored inside it. Its exit is captured with `set +e … set -e`, never `\|\|`, because bash ignores `set -e` inside a `\|\|` list. On failure: a bash-rendered `pending phase-error` block, a counter in the state dir, and `needs-human` on every actionable PR at the third consecutive failure. | §6.5, §6.8 |
| AR8 | The §7.2 check `vendors_run == required` for `request_changes` rejects valid mixed results (ADR A2). In those, `vendors_run` omits the failed vendor (`:927`). The record would then read as absent forever, so the PR is re-reviewed at full vendor cost every cycle. | `request_changes` requires `vendors_run` to be a non-empty, order-preserving subset of `vendors_required`. Equality applies to `approve` only, as S1a already enforces. The tier-to-vendor-set consistency check uses `vendors_required`. | §7.2 |
| AR9 | The draft said tier-null holds "are not persisted by S1a today". They are: §5.7 step 4d writes them at `-agy+codex.json` (TD-S1a T30 e). Only the step 4c collision result is not persisted. | The statement is corrected. The tier-null rule is unchanged. | §7.2 |
| AR10 | A records or runs dir that fails `_private_dir_ok` makes every record read as absent. The runner then re-reviews every cycle with no bound on vendor spend, because `mkdir(exist_ok=True)` never repairs the mode. | The writer checks `_private_dir_ok` before any record, counter, raise, run-dir or findings write. On failure it returns `pending state-write-failed`, which the phase strikes to a hold (AR1). | §3.1, §7.1 |
| AR11 | In G1c, a valid record with `tier: null` would crash `max()`. §8.2 step 4 also said a `write_raise` failure "does not turn an accept into a refusal", but the raise is only written on the refusal path. | Records with a null tier are skipped as tier inputs. The step 4 wording is corrected. | §8.2 |
| AR12 | The interim prose covered only exit 4. `review_worktree.sh` exit 3 (fetch failed) and 5 also have to mean "do not route". The existing cron-prompt rule "exit 4 means re-read head_sha and start again" would otherwise tell the model to route the old findings against the new head. Cleanup was not stated for every path. | Any non-zero exit means `pending`, with no route. This overrides the generic exit-4 rule for the OSR route only. `--cleanup --pr N` runs on every path. | §9.3 |
| AR13 | §2.3 named `scripts/automation/merge_authority.py`, which does not exist. | Corrected to `scripts/automation/lib/merge_authority.py`. | §2.3 |
| AR14 | The mutant arithmetic was 86 + 21 + 36 = 143 ≠ 146. The equivalent list had 35 names, including `_main_20`, which is not in the set. Most proofs did not match the mutated line. | The buckets are recomputed exactly against `osr-dispositions.md` (71 + 54 + 21 = 146): 118 kill, 28 equivalent candidates (Q2, human), 0 deferred. AR22 later revises this to 119 and 27. | §11 |
| AR15 | §15 called C4 a startup gap. AD-9 assigns the integrity check to S1b explicitly ("The integrity check itself is S1b scope"), so it is not a gap. No S1a approval is orphaned, because the functions S1b modifies are reviewed as part of S1b's own diff. | §15 is rewritten. No `startup-artifact-gap` issue is required. | §15 |
| AR16 | G1c runs inside the overseer model's sandboxed Bash, via `bootstrap/pr_review.sh`. If the sandbox maps the uid differently or masks `.claudetmp/overseer-authority/`, every approve refuses. That fails closed, but the overseer can then never auto-approve. | A post-merge live check, before S2, confirms that G1c accepts at least one approve under the sandbox. | §13 |
| AR17 | (Coder deviation 1, ratified 2026-11-19.) `bin/hos-cron` may not contain a quoted hold-label literal (`tests/framework/test_selection_call_sites.py:259`). The phase also needed the head for `mark-hold-label`, and a no-runner path for synthetic results. | The helper gains three subcommands. `held` reads the PR detail JSON on stdin and prints `1\|0`; unreadable input prints `0`, which is safe because the runner re-reads labels and returns `skipped-held`. `mark-args` prints the line's head or nothing. `ingest --synthetic <config-error\|phase-error\|untrusted-checkout\|runner-unbounded>` holds or strikes with no runner call. **T-PH-20 must also pin `ph.HELD_LABELS == osr.HELD_LABELS`.** | §3.2, §12.2 |
| AR18 | (Coder deviation 2, ratified.) §5.3 item 4's "`vendors` null iff `tier` null" contradicts S1a: the §5.7 step 4d hold is written with `tier: null` and the placeholder `vendors_required: ["agy","codex"]`, and `_result_from_record` emits `vendors="agy+codex"` for it. | `tier` non-null requires `vendors` non-null. `tier` null permits `vendors` null or a VENDORSETS string. A non-null `vendors` with a null `tier` is a storage placeholder and always renders `vendors=-` (helper `render_line`, and `check_marker` for the marker). It is never a requirement. | §5.3 |
| AR19 | (Coder deviations 3-5, ratified.) T-G1c-10..12 exercise G1c's defence-in-depth branch (step 2h), which the real loader makes unreachable, so they monkeypatch `load_record`. T-OSR-41's draft wording was inverted: `_atomic_write_text_16` drops `dir=parent`, so the **correct** code ignores a bad global `tempfile.tempdir` and the mutant fails. The T-CR-14 "< 300" clamp branch is unreachable, because `_lock_ceiling >= 3600` makes the clamp at least 3300. | T-G1c-10..12 stand. **One real-file companion is required:** the same three approve records written to disk through the harness give `second_review_record_missing` end to end. T-OSR-41 asserts the write succeeds with `tempfile.tempdir` pointing at a nonexistent path. T-CR-14 tests the 3300 clamp and a non-integer `SECOND_REVIEW_VENDOR_TIMEOUT` → `config-error`. The `>= 300` guard stays as dead defence in depth. | §11.3, §12.1, §12.3, §12.5 |
| AR20 | (Coder deviations 6-7, ratified.) `sanitize` neutralises mentions and links before the 2,000-character cut. A corrupt `phase-aborts` counter is read as 2. The marker is appended as `body.rstrip("\n") + "\n\n" + marker + "\n"`. | Neutralising first keeps the length bound exact. The cut can only remove characters or append `…`, so it cannot create a mention, a link or a marker. A corrupt counter becomes 3 on this abort and labels the PRs, which fails closed on suspicious state. The `rstrip` only normalises trailing newlines, so the interim marker's `MULTILINE` regex and G4's byte compare are unaffected. D-4 refusing a forged `hos-overseer-check` line is the §3.3/§10.3 requirement, not a deviation. | §3.3, §5.4, §6.8, §10 |
| AR21 | (Coder deviation 8, ratified.) The T-INT tests differ from the draft scenarios but match the code (`stdin=DEVNULL`, so the sentinel must **not** reach the child). | The 8 env and timeout mutants are killed in-process. T-INT-02 (an env passed is exactly the env seen) kills `_default_run_cmd_7/14/21`. T-INT-04 (a `Deps.run_cmd` spy asserts the diff call's `timeout == GIT_TIMEOUT` and `env["GIT_CONFIG_GLOBAL"]`) kills `_Ctx.run_4` and `_changed_paths_12/13/15/16`. T-INT-01 also kills `_default_run_cmd_8` (stdin). | §11.3, §12.1 |
| AR22 | (Coder deviation 9, ratified.) The architect's §11.5 proof for `_atomic_write_text_28` was wrong: `_serialize_findings` (`:793`) uses `ensure_ascii=False`, so under an ASCII locale codec an implicit encoding raises. `test_osr50` kills it. | `_atomic_write_text_28` moves to the kill bucket. **Kill bucket 119, Q2 candidates 27.** | §11.2, §11.5, Q2 |
| AR23 | (Built-code review, ratified 2026-11-21.) When `render` fails, the fallback renders `verdict=pending reason=phase-error` and labels every non-held PR. §6.5 said `hold phase-error`. Separately, step 4a's "`reason=phase-error` → pending" bullet also matches the `verdict=hold reason=phase-error label=applied` line written on an `ingest` failure, so no HUMAN_REQUIRED comment explains the label. | Ratified. Both fail closed, because the label is applied. **S1c** keys the step 4a pending bullet on `verdict=pending reason=phase-error`, so a `hold` line gets the hold handling. | §3.5, §6.5 |
| AR24 | (Built-code review, ratified 2026-11-21.) `pr_review_cli` calls `_load_osr()` on every `submit-verdict`, not lazily in the approve branch as §3.3 said. The D-4 prefix check and the comment-path marker both need the module, so §3.3 contradicted itself. | Ratified. If the module fails to import, every verdict exits 1, which is acceptable. | §3.3 |
| AR25 | (Security review of the built code, 2026-11-21, CWE-345.) §7.1 named "the sandbox policy and the protected-surface gate" as the control for same-uid record forgery. Neither exists for runtime state. `denyWrite` covers only `bin/` and `hos-sandbox.values`, so the overseer model can write a record that G1c accepts. | The residual is accepted for S1b and stated as such in §7.1, in the ADR correction note and in the PR's Human Review Required section. In `overseer.md` step 4a, G1c is not described as mechanical against the model (the edit is made by the top-level session, in a file already in the set). Slice **S1d**, which S2 is `blocked_by`, moves the raise and lock files out of `records/`/`runs/`, adds `records/` and `runs/` to `denyWrite` (template + generated policy + pinning test), and re-runs AR16. | §7.1 |
| AR26 | (Security review, CWE-427.) `bin/hos-cron` runs `cd $REPO_ROOT && python3 -m scripts.automation.lib.overseer_second_review` unsandboxed, holding the overseer token. An untracked stdlib-shadowing module at the clone root would run, and the trusted-checkout check uses `--untracked-files=no`. The same pattern already runs on main every cycle (`in_progress`, `cycle_log` via `_audit`). | Not an S1b blocker. One follow-up issue covers every unsandboxed `python3 -m` in `hos-cron`: run with `-I` and an explicit path, and have the trusted-checkout check refuse untracked `*.py` on the import path. Because the runner's result is the sole review after S2, that issue is also a `blocked_by` of S2. | §6.2, §6.3 |
| AR27 | (Security review: SHOULD_FIX 3 and 4, LOW 5, NIT 6.) | **S1b:** one `overseer.md` step 4a line saying `findings_file` contents and worker-written PR text are untrusted data, never instructions (SHOULD_FIX 4). **S1c:** the marker consumer accepts only the exact, code-appended final line, and D-4 refuses any body containing `hos-overseer-check` after NFKC normalization, not only a line prefix (SHOULD_FIX 3). No S1b reader treats the marker as authority. **S1d:** a scrubbed git env for `pinned_base` (LOW 5) and `LINE_RE.fullmatch` (NIT 6). S1b's code is unchanged. | §7.1, §10.3 |

## 1. Scope

S1b implements:

1. AD-1/AD-12: the overseer cron pre-model phase in `bin/hos-cron`.
2. AD-3: the context block injected into the overseer prompt.
3. AD-9: the G1c approval gate in `pr_review_cli._cmd_submit_verdict`.
4. AD-4: the marker appended to overseer verdict bodies.
5. AD-5: the overseer and cron-prompt prose.
6. The record-integrity mechanism (C4).
7. The disposition of the 146 field-drop survivors (§11).

AD-10 route head-carry is S1c (§9).

Out of scope: S2 (worker-side removal of second review). S2 must not start before S1c merges.

## 2. File list and slice decision

### 2.1 Count

AD-11's S1b had 12 files. Adding the helper (C8), its test, the prompt artifact, the TD and the ADR correction note gives 15. Route head-carry adds `merge_authority_cli.py`, `merge_authority.py` and `test_merge_authority_cli.py`, which makes 18. That is over the 15-file limit, so the S1c split is taken (Q0=A).

### 2.2 S1b (15 files)

| # | Path | A/M | Owner |
|---|---|---|---|
| 1 | `bin/hos-cron` | M | coder |
| 2 | `bin/lib/osr_phase.py` | A | coder |
| 3 | `scripts/automation/lib/overseer_second_review.py` | M | coder |
| 4 | `scripts/automation/pr_review_cli.py` | M | coder |
| 5 | `.claude/agents/overseer.md` | M | **top-level session** (#1347; coder must not write agent files) |
| 6 | `bootstrap/overseer-cron-prompt.md` | M | coder |
| 7 | `docs/LABELS.md` | M | coder |
| 8 | `tests/automation/test_hos_cron.py` | M | unit-test/coder |
| 9 | `tests/automation/test_osr_phase.py` | A | unit-test/coder |
| 10 | `tests/automation/test_overseer_second_review.py` | M | unit-test/coder |
| 11 | `tests/automation/test_pr_review_resolution.py` | M | unit-test/coder |
| 12 | `tests/automation/test_pr_review_wrapper.py` | M | unit-test/coder |
| 13 | `docs/v0.7.0/TD-2357-S1b-overseer-second-review-wiring.md` | A | technical-design |
| 14 | `docs/v0.7.0/ADR-2357-overseer-second-review.md` | M (correction note C1–C8 summary; architect authors) | architect |
| 15 | `prompts/scripts/automation/lib/overseer_second_review.v2357.md` | M (append the S1b prompt) | coder |

`SCRIPTS-INDEX.md` stays untouched. The generator scans `bin/` top level only, so `bin/lib/osr_phase.py` is not indexed. The first docstring lines of files 3 and 4 must not change. Check with `scripts/framework/regen_all.sh --check`. If that check reports drift, the coder stops and reports. Do not add a 16th file.

Commits are ≤10. Suggested commit sequence: (1) runner changes and tests; (2) helper and tests; (3) G1c and marker and tests; (4) hos-cron phase and tests; (5) prose (prompt, LABELS); (6) agent file (top-level session); (7) docs/ADR/prompt artifact.

### 2.3 S1c (4 files, separate PR, must merge before S2)

`scripts/automation/merge_authority_cli.py`, `scripts/automation/lib/merge_authority.py` (AR13), `tests/automation/test_merge_authority_cli.py`, and the prompt artifact for `merge_authority_cli`. The contract is in §9.

## 3. Per-file changes (S1b)

Line numbers refer to the files at `origin/main` `aebc96aab`.

### 3.1 `scripts/automation/lib/overseer_second_review.py`

| Location | Change |
|---|---|
| constants block, lines 47–110 | Add `RESULT_KEYS: frozenset[str]`: the §5.8 keys plus `pending_count` and `pending_last_reason`. Add `CHECK_MARKER_PREFIX = "<!-- hos-overseer-check"`. Add `FINAL_REASON_FOR_VERDICT = {"approve": "ok", "request_changes": "findings", "not-required": "tier-below-medium"}`. |
| `_read_json_dict` line 267 | New keyword `private: bool = False`. When true, after `os.fstat(fd)`, require `st.st_uid == os.geteuid()` and `st.st_mode & 0o077 == 0`. On failure return `None`, the same as every other read failure. |
| new `_private_dir_ok(path) -> bool`, placed after `_read_json_dict` | `os.lstat`; require `stat.S_ISDIR`, not `S_ISLNK`, `st_uid == os.geteuid()` and `st_mode & 0o077 == 0`. On any `OSError` return `False`. Undecorated. |
| `_findings_shape_ok` line 332 | Require `_private_dir_ok` on the `runs/` dir and on the run dir. Read the findings file with `private=True`. |
| `load_record` lines 344–402 | Require `_private_dir_ok(records_dir)`. Read with `private=True`. Add the self-consistency checks from §7.2. On any failure return `None`. |
| `read_raise` line 464 | Read with `private=True`. Invalid behaviour is unchanged: the caller treats it as HIGH. |
| `sanitize` line 536 | After the existing step 5, add step 6 (§5.4). |
| `_Ctx` line 968 | Two new fields: `pending_count: int \| None = None` and `pending_last_reason: str \| None = None`. |
| `_count_pending_locked` line 1153 | After the counter file is successfully written, set `ctx.pending_count` and `ctx.pending_last_reason` from the same values that were written. Assign the values, do not re-read the file. When the counter is skipped (`_count_pending` lock failure, `:1218-1220`), both stay `None`, and the phase strikes that line (AR1). |
| `_result` line 995 | Emit `pending_count` and `pending_last_reason` from `ctx`. Assert, outside `-O`, that the key set equals `RESULT_KEYS`. Use an explicit `if … raise RuntimeError`, not `assert`. |
| `_result_from_record` line 1017 | Emits both new keys from `ctx` when `reused=False` and as `None` when `reused=True` (AR5). A stuck-path hold written by §5.7 step 4d therefore carries the count that triggered it. A reused record, including §5.7 step 4a's return, carries `None`. The step 4c non-persisted hold goes through `_result` and carries the count. |
| `_atomic_write_text` line 238, `runs.mkdir` line 1358 | **AR10.** Before writing, require `_private_dir_ok(parent)` after the `mkdir`. For the run dir, require it on `runs/` too. On failure raise `OSError`. The existing `_run` handler (`:1490-1492`) maps that to `pending state-write-failed`, and the phase strikes it (§6.6). A dir with a bad mode therefore ends in a hold, not a re-review every cycle. |
| new `pinned_base(repo_root, base_tip, head) -> str \| None` | Runs `git merge-base <base_tip> <head>` through `_default_run_cmd` with `GIT_TIMEOUT`, `cwd=repo_root`. Returns the 40-hex stdout or `None`. Requires 40-hex inputs. Undecorated. |
| new `approval_gate(repo_root, *, repo, pr, head_sha, base_tip, argv_tier, lock_timeout=10.0) -> GateResult` | Algorithm in §8. `GateResult` is a `NamedTuple(ok: bool, reason: str \| None, diag: dict, record: dict \| None, raise_written: bool)`. |
| new `check_marker(*, pr, head_sha, record) -> str` | Renders the AD-4 marker (§10). |
| `main` line 1566 | No new subcommand. G1c and the marker are imported in-process. |

None of the new functions may be decorated: mutmut 3.8 produces zero mutants for decorated functions.

### 3.2 `bin/lib/osr_phase.py` (new; stdlib-only; invoked `python3 -I`)

It must not import `scripts.automation.lib`. It is invoked with `-I` from `$_HOS_CRON_DIR/lib/`, like `usage_pause.py`. The vocabularies it checks are duplicated literals, and a drift test (T-PH-20) pins them against the runner's sets.

Subcommands (argparse; exit 0 on success, 2 on usage error, 1 on any other failure). Every failure is fail-closed at the bash side (§6.5):

| Subcommand | Inputs | Output (stdout) |
|---|---|---|
| `order --state-dir D --prs "N N N"` | strike/defer state | PR numbers, space-separated: budget-deferred PRs first, then ascending |
| `budget --elapsed E --uncached-ran 0\|1 --per-pr P --budget B` | | `RUN` when `uncached-ran == 0` or `E + P <= B`, else `CACHE_ONLY` (AD-12, AR6) |
| `ingest --state-dir D --runs-dir R --pr N --rc RC --cache-only 0\|1 --held 0\|1 --out F --err F --scratch S` | runner stdout/stderr files, rc | `ACTION=label\|none UNCACHED=0\|1` (one line) and writes `S/pr<N>.line.json`. `UNCACHED=1` when the call was not `--cache-only` and the result is not `reused=true`, not `not-required`, and not `skipped-held`. A non-zero rc also counts as uncached, because it may have spent the full per-PR time. |
| `label-result --scratch S --pr N --result applied\|failed` | | none; updates `S/pr<N>.line.json` |
| `render --scratch S --prs "N …" --held "N …"` | | the context block (§5) |
| `defer --state-dir D --pr N` | | none; records the PR as budget-deferred |

### 3.3 `scripts/automation/pr_review_cli.py`

| Location | Change |
|---|---|
| between G2 (ends line 880) and G3 (line 882) | G1c (§8). Runs only when `args.event == "approve"`. Import `scripts.automation.lib.overseer_second_review as _osr` inside the branch (lazy import), so non-approve paths do not depend on the module. |
| `_verdict_payload_base` line 672 | Callers add `payload["second_review"] = diag` on both refusal and success when G1c ran. Its signature does not change. |
| D-4 marker refusal, lines 934–946 | Also refuse any body line whose `lstrip()` starts with `_osr.CHECK_MARKER_PREFIX`. Reuse the existing refusal reason string at that site and the same exit (2). |
| after the interim append, lines 966–968 | When `args.app == "overseer"` (approve and comment): `body = body + "\n\n" + _osr.check_marker(pr=…, head_sha=pre.head_sha, record=sel) + "\n"`. `sel` is selected per §10.2. |
| success payload, line 1158 | Includes `second_review` (diag) and `check_marker` (the rendered line). |

### 3.4 `bin/hos-cron`

| Location | Change |
|---|---|
| pre-filter detail jq, lines 1599–1600 | `{ms: .mergeable_state, d: .draft, labels: [.labels[].name]}`. A PR carrying `needs-human` or `hos-halt` is appended to new var `_HOS_HELD_PRS`. It stays in `HOS_ACTIONABLE_PRS` (the model still reports on it), but the phase skips it (`verdict=skipped-held`). |
| new block between line 2324 (end of worker baseline) and line 2327 (`# ── Cycle start`) | The OSR phase (§6). |
| immediately before line 2541 | `touch "$_LOCK_DIR"` (heartbeat). |
| injection, lines 2541–2544 | After the pre-filter `---` line, `cat "$_OSR_BLOCK"` when the phase ran. |

### 3.5 Prose files

- **`.claude/agents/overseer.md`** (top-level session, not coder). New step 4a paragraph "Overseer-run second review (#2357)", inserted after line 401 and before the "Incomplete review chain" paragraph at line 406. It covers:
  - read the OSR line for the PR;
  - `verdict=approve` is necessary but not sufficient;
  - `request_changes`: route with the findings file per §9.3 interim prose;
  - `hold`: with `label=applied`, post the HUMAN_REQUIRED comment verdict. With `label=failed` (or `-`), apply `needs-human` with `edit_issue.sh`, then post it (ADR AD-3 correction note). With `label=existing`, post nothing new;
  - `reason=phase-error` or no block at all: every PR is `pending`;
  - `pending`: take no action this cycle;
  - `skipped-held`: no second-review action;
  - never edit records;
  - G1c refusal reasons and what each means. `second_review_record_unverifiable` is handled like `second_review_record_missing`: do not approve, change no label, re-evaluate next cycle (Q4).
- **`bootstrap/overseer-cron-prompt.md`.** One sentence in the "Step 1 — Review open PRs" preamble (about line 52): "The `[hos-cron overseer second review (#2357)]` block, if present, is authoritative for second-review state; follow `overseer.md` step 4a."
- **`docs/LABELS.md`** line 30, `needs-human` row: add `hos-cron overseer phase (#2357 hold)` to the writers list.

## 4. State and counter locations

| State | Path | Writer | Reader | Lifetime |
|---|---|---|---|---|
| second-review records | runner `records/` (S1a §7) | runner `_write_record` | runner `load_record`, G1c `approval_gate`, marker selection | S1a |
| runs / findings | runner `runs/<id>/findings.json` | runner `_write_findings` | runner `_findings_shape_ok`, model → route | S1a |
| raise file | S1a §7 | `write_raise` (runner and G1c) | `read_raise` only (P6) | S1a |
| pending counter | S1a §7 | `_count_pending_locked` | same, and surfaced via result keys `pending_count`/`pending_last_reason` (C3) | S1a |
| **strike state** | `$_HOS_DIR/osr-phase/$PROJECT/strikes/pr<N>.json`, dir 0700 | `osr_phase.py ingest` | `osr_phase.py ingest`, `order` | deleted on non-strike result; reset on head change |
| **defer state** | `$_HOS_DIR/osr-phase/$PROJECT/deferred.json` | `defer`, `ingest` (removes on run) | `order` | cleared when the PR runs |
| scratch | `mktemp -d` under `$TMPDIR` | phase | phase | `trap` removes it at phase end |

The strike directory is outside `records/`, as AD-12 requires.

Strike file schema: `{"schema": 1, "pr": N, "head": sha40|null, "count": int≥1, "last_reason": token, "updated_at": "%Y-%m-%dT%H:%M:%SZ"}`. Writes are atomic (mkstemp in the same dir, fsync, `os.replace`). A strike write failure makes the result `hold state-write-failed` immediately (`persisted=false`, label). The helper reads the strike file with O_NOFOLLOW and the same owner/mode check as §7.1. A file that fails to read or parse counts as `count=0`, and the helper also emits a WARN on stderr.

## 5. Context block

### 5.1 Shape

```
[hos-cron overseer second review (#2357)]
OSR pr=#<N> head=… base=… tier=… vendors=… verdict=… reason=… findings_file=… reused=… persisted=… count=… last_reason=… label=…
… one line per PR in HOS_ACTIONABLE_PRS order …
---
```

When the phase guard is false (§6.1), there is no block at all. The model then treats every PR as `pending phase-not-run`. The overseer.md prose states this, and G1c still refuses an approval without a record.

### 5.2 Line format and regex

Each key appears exactly once, in this order, separated by single spaces:

```
^OSR pr=#[1-9][0-9]{0,6} head=([0-9a-f]{40}|-) base=([0-9a-f]{40}|-) tier=(LOW|MEDIUM|HIGH|CRITICAL|-) vendors=(none|agy|agy\+codex|-) verdict=(approve|request_changes|not-required|hold|pending|skipped-held) reason=[a-z0-9:-]{1,64} findings_file=(/[A-Za-z0-9._/+-]{1,512}|-) reused=(true|false) persisted=(true|false|-) count=([1-9][0-9]{0,5}|-) last_reason=([a-z0-9:-]{1,64}|-) label=(applied|failed|existing|-)$
```

Field sources:

| Field | Source |
|---|---|
| pr | runner `pr` (must equal argv N) |
| head | `head_sha` or `-` |
| base | `base_sha` or `-` |
| tier | `tier` or `-` |
| vendors | `vendors` (already a VENDORSETS string such as `agy+codex`); `-` when tier is null |
| verdict | `verdict` (the runner may itself return `skipped-held`, AR3), or the phase's `skipped-held` |
| reason | `reason`, or the phase reason (§6.6) |
| findings_file | `findings_file` or `-` |
| reused | `reused` |
| persisted | `true` when `record` is non-null; `false` for holds with null record or phase-synthesized holds; `-` for skipped-held |
| count | `pending_count` (a counted pending, or a runner `pending-stuck` hold with `reused=false`, AR5), or the strike count when the verdict came from a phase strike, including the phase's `pending-stuck` hold; `-` otherwise |
| last_reason | `pending_last_reason`, or the strike last_reason; `-` otherwise |
| label | `applied` / `failed` from the label step; `existing` when the verdict is hold and the PR already carries needs-human/hos-halt (the runner's held path, `:1452-1459`, or `_HOS_HELD_PRS`), with no label call; `-` otherwise |

Phase-synthesized results (runner not called, or its output rejected) render `head=- base=- tier=- vendors=- findings_file=- reused=false`.

### 5.3 Validation in `ingest` (runner stdout → line)

The runner stdout must be exactly one line of JSON object (trailing newline allowed), at most 64 KiB. Otherwise the result is `invalid-line` (strike). The checks, in order (the first failure wins):

1. The key set equals the duplicated `RESULT_KEYS` exactly.
2. `check == "second-review"`, `schema == 1`, `pr == N`.
3. `head_sha` and `base_sha` are each 40-hex or null. `range` is null, or exactly `f"{base_sha}..{head_sha}"` with `base_sha` non-null.
4. `tier` ∈ TIERS or null. `vendors` is a string in VENDORSETS, or null. A non-null `tier` requires a non-null `vendors`. A null `tier` permits either; that is S1a's step 4d placeholder, and it renders `vendors=-` (AR18).
5. `verdict` ∈ {approve, request_changes, not-required, hold, pending, skipped-held}. `status` ∈ the S1a §5.6 status set. `reason` ∈ the union of `HOLD_REASONS`, `PENDING_COUNTED`, `PENDING_UNCOUNTED`, the final reasons (`FINAL_REASON_FOR_VERDICT` values) and `held-label`, and is consistent with the verdict. `skipped-held` pairs only with `held-label`, `status: null` and `record: null` (AR3).
6. `findings_file` is non-null iff `verdict == "request_changes"`. When non-null, it is an absolute path, matches the regex path class, and is under the runner `runs/` dir. The helper is given that dir via `--runs-dir`. Bash passes `$REPO_ROOT/.claudetmp/overseer-authority/second-review/runs`, which is `overseer_second_review.runs_dir()` (`:199`), not anything under `_HOS_DIR` (AR4). Check with `os.path.realpath` prefix plus a `/`.
7. `record` is an absolute path string under `records/` for every `approve`, `request_changes`, `not-required` and persisted `hold`. It is null for `pending`, `skipped-held` and the non-persisted `hold pending-stuck` (TD-S1a §5.7 step 4c) only (AR4).
8. `hold_label_applied` is a bool when `verdict == "hold"` and `record` is non-null; otherwise null.
9. `pending_count` is an int ≥1 or null when `verdict == "pending"` and `reason ∈ PENDING_COUNTED`. Null means the runner's counter was skipped, and the phase strikes the line (AR1). It is an int ≥3 when `verdict == "hold"`, `reason == "pending-stuck"` and `reused == false`. It is null otherwise. `pending_last_reason` is non-null exactly when `pending_count` is, and is in `PENDING_COUNTED` (AR5).
10. `reused` is a bool.

### 5.4 Sanitization (runner `sanitize`, step 6; also applied by `osr_phase.render` to every token it did not validate against a closed regex)

After the existing step 5:

- insert U+200D after every `@` that is followed by `[A-Za-z0-9_-]`;
- replace `](` with `]‍(`;
- replace `![` with `!‍[`.

The OSR line is regex-closed, so it needs no sanitization at render time. The rule is a defence for the diag and payload fields, which do reach a human-visible surface.

## 6. Phase algorithm (bash `bin/hos-cron`, new block before `# ── Cycle start`)

### 6.1 Guard

Run only when `ROLE == overseer`, `HOS_ACTIONABLE_PRS` is non-empty, and `$REPO_ROOT/scripts/automation/lib/overseer_second_review.py` exists. If any is false, skip the phase, write no block, and log `[hos-cron] osr phase skipped: <why>` to stderr.

### 6.2 Setup

1. `_OSR_SCRATCH="$(mktemp -d)"` with `trap` cleanup chained onto the existing EXIT trap. Never replace the trap.
2. `_OSR_STATE="$_HOS_DIR/osr-phase/$PROJECT"`, created with `mkdir -p` and `chmod 700`. If that fails, every PR gets `hold config-error` with a label (§6.5).
3. Timeout binary: `timeout` or else `gtimeout` via `command -v`, into `_OSR_TB`. If neither exists, every non-held PR gets a `runner-unbounded` strike and the runner is never called.
4. `_OSR_PER_PR_MAX = 3*SECOND_REVIEW_VENDOR_TIMEOUT + 300`, clamped to `_lock_ceiling - 300` (lock ceiling at lines 324–327). If the clamp would drop it below 300, every PR gets `hold config-error`.
5. `_OSR_BUDGET` comes from `_conf_val "<project>_overseer_sr_budget"` (line 181), defaulting to `HOS_CRON_MAX_SECONDS`, and a value of 0 is treated as 3600. Floor it at `_OSR_PER_PR_MAX`. A non-integer means `config-error` for all PRs.
6. Trusted checkout (ADR AD-1, the same three checks as the runner's `_trusted_checkout`, `:1231-1244`): `git symbolic-ref --short HEAD` is `main`, `git status --porcelain --untracked-files=no` is empty, and `HEAD == refs/remotes/origin/main`. On failure every non-held PR gets an `untrusted-checkout` strike (Q3=A), plus `_audit cycle-osr-untrusted-checkout`, and the runner is never called.

### 6.3 Per-PR loop

The order comes from `osr_phase.py order`. Held PRs (`_HOS_HELD_PRS`) produce `skipped-held` and are not looped. For each other PR N:

1. `_hos_refresh_token` (line 1127), then `touch "$_LOCK_DIR"`.
2. `osr_phase.py budget --elapsed $(( SECONDS - _OSR_T0 )) --uncached-ran $_OSR_UNCACHED_RAN --per-pr $_OSR_PER_PR_MAX --budget $_OSR_BUDGET` (AR6; `_OSR_T0` is bash `SECONDS` at phase start). `RUN` gives `_cache=""`, and `CACHE_ONLY` gives `_cache="--cache-only"`. This is AD-12's rule: the first uncached review of a cycle always runs, and after the budget is spent every remaining PR is still called with `--cache-only`. That costs no vendor call, so a PR with an existing final record stays approvable this cycle.
3. A `--cache-only` call that returns `pending budget` is recorded with `osr_phase.py defer --pr N` by `ingest`. That PR runs first next cycle (`order`), and at least one uncached review runs every cycle, so `budget` is bounded by ordering. It is not counted.
4. `rc=0; (cd "$REPO_ROOT" && "$_OSR_TB" --kill-after=30 "$_OSR_PER_PR_MAX" python3 -m scripts.automation.lib.overseer_second_review run --pr "$N" $_cache) >"$_OSR_SCRATCH/pr$N.out" 2>"$_OSR_SCRATCH/pr$N.err" || rc=$?`. This is the **only** runner invocation in the phase (binding item 1).
5. `osr_phase.py ingest --pr N --rc $rc --cache-only 0|1 --held 0|1 --runs-dir <literal> …`. Parse its single `ACTION=(label|none) UNCACHED=(0|1)` line with an anchored bash regex. Set `_OSR_UNCACHED_RAN=1` when `UNCACHED=1`.
6. If `ingest` exits non-zero or its output fails the regex, write the phase-error line (§6.5) for N.

### 6.4 Post-loop

For each PR with `ACTION=label`:

1. `"$_OSR_TB" --kill-after=10 120 bash bootstrap/edit_issue.sh --number N --add-label needs-human --app overseer`. If it fails: `WARN` on stderr, `_audit cycle-osr-hold-label-failed`, and result=failed.
2. If it succeeded and the line has `persisted=true`, run `(cd "$REPO_ROOT" && "$_OSR_TB" --kill-after=10 120 python3 -m scripts.automation.lib.overseer_second_review mark-hold-label --pr N --head <line head> --applied true)` (AR2: `--head` and `--applied` are required, `:1560-1562`). Exit 0 is fine. Exit 3 with `persisted=true` is a WARN plus audit. Any other exit is a WARN plus audit. The label stands either way. With `persisted=false` (phase-synthesized holds and the runner's step 4c hold), `mark-hold-label` is not called, because there is no record and no head for it.
3. `osr_phase.py label-result --pr N --result applied|failed`.

Then:

4. `touch "$_LOCK_DIR"`, then `_hos_refresh_token`.
5. `osr_phase.py render … > "$_OSR_BLOCK"`. Bash then re-validates every `OSR ` line with the §5.2 regex (`[[ =~ ]]`). If render fails or any line fails the regex, the whole block is replaced by phase-error lines for every PR, and every non-held PR is labelled (one pass of steps 1–3 for those not yet labelled).

### 6.5 Fail-closed table

| Failure | Result |
|---|---|
| runner rc ≠ 0 (incl. 124 timeout, 137 kill, 1 exception, 2 usage) | strike `runner-failed` |
| runner rc 0 but stdout fails §5.3 | strike `invalid-line` |
| runner result `pending` with a reason in `PENDING_COUNTED` and `pending_count` non-null | the runner's own count, surfaced with `count=`. Pending-stuck at 3 is the runner's hold. No phase strike. |
| runner result `pending` with `lock-busy`, `state-write-failed`, `config-error`, `github-error` or `untrusted-checkout` (all `PENDING_UNCOUNTED` in S1a, `:98-109`), or a `PENDING_COUNTED` reason with `pending_count` null (counter skipped) | strike, with `last_reason` set to the runner's reason (AR1; binding item 2) |
| runner result `pending` with `budget`, `head-moved`, `pr-not-found` or `pr-not-open`, or `skipped-held` | neutral: no strike and no reset. `budget` is bounded by ordering, `head-moved` by the new head, and the other two mean the PR has left the actionable set. |
| helper `ingest` failure | `hold phase-error`, label, persisted=false |
| strike write failure | `hold state-write-failed`, label |
| `render` failure / regex failure | bash-rendered `verdict=pending reason=phase-error` for all PRs; `needs-human` on every non-held PR not already labelled in the phase (AR23; corrected by TD-2357-S1c, carry item 4) |
| state dir / config invalid | `hold config-error` for all PRs, label |
| phase subshell aborts (§6.8) | bash-rendered `pending phase-error` for all PRs; at the 3rd consecutive abort, `needs-human` on every actionable PR |
| no timeout binary | strike `runner-unbounded` |
| untrusted checkout | strike `untrusted-checkout` (Q3) |

Every command inside the phase that may fail is in a `|| rc=$?` or `if` context. An unexpected abort of the phase is handled by §6.8. It **never** ends the cycle (ADR AD-1: "The phase never aborts the cycle. The model still runs"; AR7).

### 6.6 Strikes

Strike reasons that the phase synthesizes are `runner-failed`, `invalid-line`, `untrusted-checkout` and `runner-unbounded`. **Runner results the phase also strikes** (AR1) are `lock-busy`, `state-write-failed`, `config-error`, `github-error` and `untrusted-checkout`, all `PENDING_UNCOUNTED` in S1a, and any `PENDING_COUNTED` reason whose `pending_count` is null. The runner counts only `PENDING_COUNTED` (`fetch-failed`, `base-unresolved`, `lock-unavailable`, `review-failed`, `diff-failed`) with a successful counter write. The phase never strikes those, so nothing is counted twice. The `state-write-failed` count lives in `$_HOS_DIR/osr-phase/` (§4), outside `records/`, as binding item 2 requires.

A strike produces `verdict=pending reason=<r> count=<n> last_reason=<r>` while n < 3. At n == 3 it produces `verdict=hold reason=pending-stuck persisted=false count=3 last_reason=<r>` and a label. The strike file is deleted by a runner `approve`, `request_changes`, `not-required` or `hold` result, or by a counted pending with a count (the runner then bounds it itself). It is reset to 1 when the runner reports a head that differs from a stored non-null head. A null stored head never resets. Neutral results (§6.5) leave it untouched. Pending is therefore bounded at 3 cycles on every path. `budget-deferred` is bounded by ordering (§6.3 step 2).

### 6.7 Exit-code mapping

| Call | Exit | Phase meaning |
|---|---|---|
| `runner run` | 0 | parse stdout (§5.3) |
| | 2 | strike runner-failed (usage: phase bug) |
| | 1 | strike runner-failed |
| | 124 / 137 (timeout) | strike runner-failed |
| `mark-hold-label` | 0 | ok |
| | 3 | expected iff persisted=false; else WARN + audit |
| | 2 / 1 / 124 / 137 | WARN + audit `cycle-osr-mark-hold-failed`; label stands |
| `edit_issue.sh` | 0 | label=applied |
| | ≠0 | label=failed, WARN, audit `cycle-osr-hold-label-failed` |
| `osr_phase.py *` | 0 | ok |
| | ≠0 | phase-error (§6.5) |
| `pr_review_cli submit-verdict` G1c | 3 | refusal (payload `refusal_reason`) |
| | 2 | D-4 forged-marker refusal |

### 6.8 Phase isolation (AR7)

The phase body runs as `set +e; ( set -euo pipefail; <phase> ); _osr_rc=$?; set -e`. It is never `( … ) || _osr_rc=$?` and never a function in an `||` or `if` context, because bash ignores `set -e` throughout such a list, including inside the subshell. The block is written only to `$_OSR_SCRATCH`, and the parent reads it only when `_osr_rc == 0`.

When `_osr_rc != 0`:

1. Bash logs a WARN and writes `_audit cycle-osr-phase-error "rc=$_osr_rc"`.
2. Bash itself writes the header, then one `OSR pr=#<N> head=- base=- tier=- vendors=- verdict=pending reason=phase-error findings_file=- reused=false persisted=- count=- last_reason=- label=-` line per PR, then `---`. `<N>` is taken from `_HOS_ACTIONABLE_PRS` after a `^[1-9][0-9]{0,6}$` check, so no helper output is used. This line matches the §5.2 regex.
3. It increments a plain integer in `$_OSR_STATE/phase-aborts`, using a write-then-`mv`. A successful phase deletes that file. At the third consecutive abort, it runs §6.4 step 1 for every actionable PR, in the parent, with the same timeout wrapper. A counter that cannot be written counts as the third abort, which is AD-12's "hold on first" alternative. A missing counter starts at 0.
4. The claude session then runs as normal. G1c still refuses every approval that has no record.

## 7. Record integrity

### 7.1 Mechanism: ownership plus mode, chosen over HMAC

Every principal that could forge a record runs as the same uid as the overseer: the worker cron, the model's Bash tool and the human shell. Any same-uid principal can also read an HMAC key, because the overseer process that signs and verifies runs unsandboxed and must be able to read it. Both vendor CLIs run sandboxed (agy `--sandbox`, codex `--sandbox read-only`) and cannot write the records dir. HMAC would therefore add key generation, rotation and missing-key failure modes without adding a boundary.

What the owner + mode check does catch:

- a record planted by a different uid (a shared machine, a mis-set checkout);
- a record made group- or other-writable, which signals tampering or a umask accident;
- a symlink swap of the dir or file (O_NOFOLLOW plus lstat).

Same-uid forgery is the residual risk, and **in S1b nothing mechanical stops it** (AR25, 2026-11-21). An earlier draft of this paragraph named the sandbox policy and the protected-surface gate as the control. That was wrong. `contract/sandbox-policy.template.json` `denyWrite` covers only `__PROJECT_ROOT__/bin` and `.claude/hos-sandbox.values`. Its `allowWrite` covers the clone, so the overseer model's Bash or Write tool can create a 0600 record under `.claudetmp/overseer-authority/second-review/records/`, and G1c accepts it. The protected-surface gate governs merges of committed files. It does not cover runtime state. In S1b the only barrier between the model and a forged record is the `overseer.md` step 4a prohibition, which is prose.

S1b accepts this residual (AR25) for three reasons. First, main has no G1c at all, so a forgeable G1c is strictly stronger than the status quo: forging a record now takes a deliberate, file-level act against an explicit prohibition, and before S1b nothing of the kind was needed. Second, the worker-side second review stays in place until S2. Third, the S1b PR is HIGH-tier protected surface, so a CODEOWNER human gates its merge. The PR body's Human Review Required section must state this residual plainly, so that the human merge is an informed acceptance.

**Required before S2 (slice S1d, AR25).** The mechanical control lands in a separate slice, which S2 is `blocked_by`:
- Move every file G1c must write from inside the model sandbox (the `pr*-raise.json` raise file, and any keyed-lock file under the state dir) out of `records/` and `runs/`, into a separate model-writable subdir. Readers' integrity checks apply there unchanged, and an invalid raise is still read as HIGH, so a forged raise can only raise the tier, never lower it.
- Add `.claudetmp/overseer-authority/second-review/records` and `.../runs` to `denyWrite`, in both the template and the generated per-clone policy (`gen_sandbox_config`), with a test pinning those entries.
- Scrub the git environment for `pinned_base` (AR27), and switch `osr_phase.LINE_RE` to `fullmatch` (AR27).
- Run AR16's live check against the new layout.

Until S1d lands, `overseer.md` must not describe G1c as mechanical against the overseer model. It is mechanical against stale, missing and non-approving records. Against the model, it is only a prohibition: no audit event detects a model write under `records/` (security round-2 NIT, 2026-11-21; S1d may add detection).

**Writer side (AR10).** A check that only readers enforce turns a bad directory mode into an unbounded loop: every record reads as absent, so every cycle re-reviews. Every writer therefore applies `_private_dir_ok` to its target dir (§3.1). A failure is `pending state-write-failed`, which the phase strikes to a hold in 3 cycles.

### 7.2 `load_record` self-consistency (in addition to S1a checks)

All of these must hold, or the record is treated as absent:

- `created_at` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` and parses with `%Y-%m-%dT%H:%M:%SZ`;
- for a final record, `reason == FINAL_REASON_FOR_VERDICT[verdict]`;
- `tier` ∈ TIERS. A null tier is allowed only for `status == hold` and `reason == pending-stuck`. S1a **does** persist such records, via TD-S1a §5.7 step 4d at the `-agy+codex` filename with `base_sha: null` (T30 e). Only the step 4c collision result is not persisted (AR9);
- `hold_label_applied` is null for finals and a bool for holds;
- `vendors_required == vendors_list(required_vendorset(tier))` for every record with a non-null tier. This ties the tier to the vendor set.
- `vendors_run`: for `approve`, equal to `vendors_required`, as S1a already checks. For `request_changes`, a non-empty subset of `vendors_required` in the same order, because a mixed result omits the failed vendor (ADR A2, `classify_run` `:927`; AR8). For `not-required`, `[]`.

The tests set `os.umask(0o022)` in a fixture. The runner already creates files at 0600 via mkstemp, so the check passes for its own writes.

## 8. G1c approval gate

### 8.1 Placement

In `_cmd_submit_verdict`, after G2 (self-authored, ends line 880) and before G3 (already-approved, line 882). It runs only for `args.event == "approve"`.

The required-check map `REQUIRED_OVERSEER_CHECKS = {"second-review": "MEDIUM"}` is a module constant in `pr_review_cli`. G1c runs when `max(argv tier, raise, record tiers) ≥ MEDIUM`, and also below MEDIUM, because it must see a `not-required` record to accept. So it always runs on approve.

### 8.2 Algorithm (`approval_gate`)

1. `head_sha = pre.head_sha` and `base_tip = pre.pr_obj["base"]["sha"]` must both be 40-hex; otherwise the result is `second_review_record_missing`. Compute `base = pinned_base(repo_root, base_tip, head_sha)`; `None` gives `record_missing`.
2. Take `head_lock(repo, pr, head_sha, timeout=lock_timeout)`. Under the lock:
   - a. `rz = read_raise(...)`. An invalid raise counts as HIGH (`raise_invalid=true`).
   - b. Call `load_record` for each of the three vendorsets with `base_sha=base`, keeping the valid ones.
   - c. `argv = LOW if args.tier == "SAFE" else args.tier`.
   - d. `T = max(argv, rz, *[r.tier for r in valid if r.tier is not None])`, then `V = required_vendorset(T)`. A null-tier hold is not a tier input (AR11). It carries `base_sha: null`, so the base-pinned `load_record` already excludes it.
   - e. With no valid record at V: refuse `second_review_tier_raise` if a valid **final** record exists at a lower vendorset, otherwise refuse `second_review_record_missing`.
   - f. If the record at V is a hold or has `verdict == request_changes`, refuse `second_review_not_approved`.
   - g. If `V == none`, accept only `verdict == not-required`. Anything else is `not_approved`.
   - h. If `V != none`, require `verdict == approve`; any other verdict (`request_changes`, `not-required`) is `not_approved`. Then also require `unresolved_findings == 0`, `binary_files == 0` and `vendors_run == V` (defence in depth). Anything else is `not_approved`. *(Text corrected by TD-2357-S1c, carry item 6; `_gate_refusal` always enforced this.)*
3. A lock timeout, lock-unavailable or `OSError` refuses with `second_review_record_unverifiable` (Q4).
4. After releasing the lock, if `required_vendorset(argv)` outranks `required_vendorset(max(rz, record tiers))`, call `write_raise(argv)`, which takes `head_lock` itself. That condition implies step 2e has already refused with `second_review_tier_raise`, so the raise is written only on a refusal. `raise_written` records whether it did. A `write_raise` failure leaves the refusal unchanged and is reported in diag (`raise_written=false`, `raise_error` = exception type name only) (AR11).

### 8.3 Check table and reason codes

| # | Check | Fails → `refusal_reason` | Exit |
|---|---|---|---|
| G1c-1 | head and base tip 40-hex; merge-base resolves | `second_review_record_missing` | 3 |
| G1c-2 | `head_lock` acquired; IO ok | `second_review_record_unverifiable` | 3 |
| G1c-3 | valid record at V exists | `second_review_record_missing` | 3 |
| G1c-4 | no valid final record exists only at a lower vendorset | `second_review_tier_raise` | 3 |
| G1c-5 | record at V is final approve or not-required (V=none) | `second_review_not_approved` | 3 |
| G1c-6 | approve: unresolved == 0, binary == 0, vendors_run == V | `second_review_not_approved` | 3 |
| G1c-7 | record `base_sha == base` (enforced by the load_record arg) | → absent → G1c-3 | 3 |
| G1c-8 | integrity (§7) | → absent → G1c-3 | 3 |

### 8.4 Diag (`payload["second_review"]`, on refusal and success)

Fields:

- `record_path`, `status`, `verdict`, `reason`, `tier`
- `tier_sources` (`{"argv", "raise", "records": [...]}`)
- `required_tier`, `required_vendors`
- `vendors_run`, `unresolved_findings`, `files_reviewed`, `binary_files`, `vendor_failures`
- `outfile`, `findings_file`, `created_at`, `base_sha`
- `raise_tier`, `raise_invalid`, `raise_written`

Every record field listed is read here. Diag is the real S1b reader for the evidence fields, which matters for the human ruling (§11). Values are run through `sanitize` before they go into diag.

## 9. S1c contract and S1b interim

### 9.1 S1c route head-carry (AD-10)

- In `merge_authority_cli._route` (line 1183), after `parse_findings_bytes` (line 1202) and **before** `canonicalize_findings_ex`, pop `reviewed_head` from the top-level object. `merge_authority.py:1727` requires the top level to be exactly `{"findings"}`, so it must be removed first.
- If present, `reviewed_head` must be 40-hex and equal the live head (line 1207, `_pin_head` 1384). A mismatch is `_Fail("head_moved", transient)`.
- Any `sr-`-prefixed entry without `reviewed_head` makes the result `findings_file_invalid`.
- `record_pr_bounce` (line 2607) gains a keyword-only `marker: str | None = None`. `_write_bounce` (1133–1176) passes the AD-4 marker with `bounced=true` when any `sr-` entry is present. `_bounce_marker` (2110) is unchanged.
- At render time, neutralize mentions in finding text and paths (§5.4 rule).
- *(Superseded: Q1 = C killed all 21 in S1b, §11.4. S1c's mutation run covers S1c's own code, TD-2357-S1c §8.)*

### 9.2 Why S1b is safe without S1c

G1c stops any approval without a matching approve or not-required record. Without head-carry, a `request_changes` route can at worst bounce against a newer head with findings reviewed at an older head. That is a stale bounce, not a wrongful merge, and the interim prose below prevents it.

### 9.3 Interim prose (overseer.md step 4a, S1b only; removed by S1c) — **superseded by TD-2357-S1c §4.1**

On `verdict=request_changes`:

1. Run `bash bootstrap/review_worktree.sh --pr N --expect-sha <OSR head>` immediately before routing, as AD-11's contingency requires. **Any non-zero exit means do not route, and treat the PR as `pending` this cycle.** That covers exit 4 (head moved), exit 3 (fetch failed), and 2 or 5. For this path only, this overrides the generic `overseer-cron-prompt.md:72` rule "exit 4 means re-read `head_sha` and start again". The OSR line is bound to the head it names, and a new head gets its own review next cycle (AR12).
2. Write a route file containing exactly `{"findings": [...]}`. Copy the `findings` entries verbatim from `findings_file`, unedited, and append any REVIEW_CHAIN entries. Omit `reviewed_head`, because `lib/merge_authority.py:1727` requires the top level to be exactly `{"findings"}` until S1c.
3. `bash bootstrap/merge_authority.sh route --app overseer --pr N --step N --findings-file <route file>`.
4. `bash bootstrap/review_worktree.sh --cleanup --pr N` on **every** path, including a non-zero exit in step 1.

The residual window between step 1 and route's own `_pin_head` is accepted. Route acts on the head it fetches itself (Rule A), so the worst case is a stale bounce, not a wrongful merge (§9.2). Mention-neutralising of `path` at render time is S1c's (§9.1). Until then, a `path` is always a file name from the PR's own changed set.

## 10. Marker (AD-4)

### 10.1 Format

```
<!-- hos-overseer-check v=1 check=second-review pr=<N> head=<sha40> tier=<T|-> vendors=<none|agy|agy+codex|-> verdict=<approve|request_changes|not-required|hold|none> bounced=false -->
```

`bounced` is always `false` in S1b (C1). The marker is appended after the interim sign-off, so the interim marker regex (multiline, prefix `<!-- hos:overseer-interim-signoff`) is unaffected. The test T-MK-04 pins that.

### 10.2 Record selection

1. The record G1c accepted (approve path).
2. Otherwise (comment path, or the approve path was refused), the newest valid record from `find_records(…, head_sha=pre.head_sha)` whose `base_sha` equals `pinned_base(...)`, or a tier-null hold.
3. Otherwise none: `verdict=none tier=- vendors=-`.

A tier-null record renders as `tier=- vendors=-`.

### 10.3 Forgery refusal

D-4 refuses any body line starting `<!-- hos-overseer-check` (exit 2), so the model cannot pre-write a marker.

## 11. The 146 field-drop survivors (human ruling 2026-11-17)

### 11.1 Re-identification

Mutant numbers shift whenever a function changes. Each survivor is therefore identified by the triple (function, original source line text, mutated line text) from `.claudetmp/2357-s1a-mutation/osr-class6.tsv`. The coder's fresh run maps each triple to its new mutant id via the mutmut diff, using `classify.py`/`dispose.py`. The triples that are not found get one of two outcomes. If the code was removed deliberately, it is reported `removed-with-code` with the commit that removed it. Otherwise it is a failure.

### 11.2 Breakdown (recomputed by the architect, AR14)

By S1a disposition text in `.claudetmp/2357-s1a-mutation/osr-dispositions.md`, the 146 are 71 "argument/expression change, not asserted", 54 "value replaced by None, not asserted" and 21 "kwarg with a default dropped". That is 71 + 54 + 21 = 146. The draft's buckets summed to 86 + 21 + 36 = 143, and its equivalent list held 35 names, one of which (`_main_20`) is not in the 146.

| Bucket | Count | Members |
|---|---|---|
| Killed in S1b | **119** | Every member of the 146 not listed in §11.5. That includes the 21 the draft deferred (Q1 = C, §11.4) and 6 the draft wrongly called equivalent: `write_raise_44`, `compute_tier_41`, `_cleanup_worktree_7`, `_atomic_write_text_17`, `_validate_entries_12` and `_validate_entries_13`. It also includes `_atomic_write_text_28`, whose architect proof failed (AR22). |
| Equivalent candidates | **27** | §11.5. These need the human's Q2 answer. |
| Deferred | **0** | |

The fresh run re-identifies every member by triple (§11.1). A candidate the fresh run reports killed leaves §11.5. A member the run cannot find is `removed-with-code` (with the commit) or a failure. The PR comment's 146 table sums exactly to 146.

### 11.3 Killed in S1b: how

| Reader | Fields it reads | Test (named in §12) |
|---|---|---|
| `osr_phase.ingest` | every result key: pr, head_sha, base_sha, range, tier, vendors, verdict, status, reason, reused, findings_file, record, hold_label_applied, pending_count, pending_last_reason | T-PH-01..12, T-INT-01..06 |
| G1c `approval_gate` | record: tier, vendors_run, verdict, status, reason, base_sha, created_at, unresolved_findings, binary_files, hold_label_applied | T-G1c-01..16 |
| G1c diag | files_reviewed, vendor_failures, outfile, findings_file, raise state | T-G1c-17, T-G1c-18 |
| marker `check_marker` | pr, head, tier, vendors, verdict | T-MK-01..05 |
| real `run_cmd` integration | cwd, argv, stdin, env of vendor invocations (`_default_run_cmd`, `_review_and_record`) | T-INT-01..06 |

Named special cases:

- `_vendor_status_5/6/7` and `classify_run_207`: a codex output whose heading sits inside a fenced block (T-OSR-40).
- `_atomic_write_text_16` (`dir=parent` dropped): with `tempfile.tempdir` set to a nonexistent path, the correct code still writes the record, and the mutant raises (T-OSR-41, AR19).
- `write_raise_44` (`_raise_valid(existing, repo, None, head_sha)`): with a HIGH raise on file, `write_raise(tier="MEDIUM")` must leave the file at HIGH. Under the mutant, the existing raise never validates, so the tier is lowered (T-OSR-43). This is the "a raise never lowers" safety property.
- `compute_tier_41` (classifier `cwd` → `None`) and `_cleanup_worktree_7` (`FETCH_TIMEOUT` → `None`): the T-INT stub records cwd and timeout (T-INT-07).
- `_atomic_write_text_17` (mkstemp `prefix=".tmp-"` dropped): `_sweep_stale_tmp` globs `.tmp-*`. An aged temp file left by a failed write must be swept by the next write (T-OSR-44).
- `_validate_entries_12/13` (exception message → `None` or `NoneType`): assert the exact stderr line `findings file failed validation (<ExcType>); holding` (T-OSR-45).
- The former Q1 21. `_default_run_cmd_7/14/21`, `_Ctx.run_4` and `_changed_paths_12/13/15/16` are env and timeout kwargs (T-INT-02 kills `_default_run_cmd_7/14/21`; T-INT-04 kills `_Ctx.run_4` and `_changed_paths_12/13/15/16`; AR21). The other 13 (`_path_of_10..15`, `_fp8_4`, `build_entries_13/14/16/67`, `_vendor_status_69/73`) are finding content: exact `path`, `slug`, order, `sr-overflow` count and `detail` asserted on the findings file, which is then round-tripped through `merge_authority.canonicalize_findings_ex` (T-OSR-46).

The real-`run_cmd` integration harness uses `Deps(run_cmd=osr._default_run_cmd)` with a stub tools dir first on PATH, and a real `git init` repo. The stub `agy`/`codex`/`git` scripts assert their cwd, argv and a stdin sentinel. Fd 0 is dup2'd to a pipe that carries the sentinel. Each stub writes its observations to a file the test reads. That is how mutants that drop `cwd=`, `input=` or `env=` kwargs get killed.

### 11.4 Deferred to S1c: none (Q1 = C)

The draft deferred 21 mutants to S1c. The architect resolved Q1 = C (see Q1), and all 21 are in the S1b kill bucket (§11.3). Deferring them would need a human answer, because the 2026-11-17 ruling requires them killed in the S1b PR.

### 11.5 Equivalent candidates (Q2, awaiting the human), 27, with proofs checked against the mutated line

| Mutant(s) | Mutation | Proof |
|---|---|---|
| `_default_run_cmd_45` | `CmdResult(..., proc.stderr)` → `None` | `CmdResult.stderr` has no reader in the module: it is set only at `:163`. |
| `_atomic_write_text_18` | mkstemp `suffix=".json"` dropped | No reader uses the temp suffix. `_sweep_stale_tmp` globs `.tmp-*`. |
| `_read_json_dict_23` | `fh.read(max_bytes + 1)` → `read(None)` | `st_size > max_bytes` was already refused after `fstat`. It differs only if the file grows after `fstat`. That is the same race-only equivalence as S1a's `_read_json_dict_25`. |
| `find_records_24` | `r.get("created_at", "")` → `r.get("created_at")` | It differs only for a record without `created_at`. §7.2 now makes such a record absent. |
| `_parse_header_2`, `_vendor_status_85/87/127` | `False` → `None` initial flag | Each flag is read only in boolean context. **The coder confirms** that none is compared with `is False`, serialized, or returned bare. Otherwise the mutant moves to the kill bucket. |
| `classify_run_34` | `.decode("utf-8", errors=…)` → `.decode(errors=…)` | `bytes.decode` defaults to UTF-8. |
| `classify_run_186/187` | `split("\n", 1)[0]` → `split("\n")[0]` / `rsplit("\n", 1)[0]` | The result is used only via `.startswith(vendor)`. All three forms start with the section's first line. |
| `_result_from_record_23/24` | `base_sha=`/`range=` kwargs dropped | `_result` falls back to `ctx.base`, which the line above sets from `rec.base_sha`, and to the range computed from it. They are equal on every reachable path (R9a, §5.7 4a/4d, held path). |
| `_result_from_record_50` | `rec.get("reason", "")` → `rec.get("reason")` | `load_record` and §7.2 require `reason` on every record. |
| `_count_pending_locked_100/101` | `tier=None`/`vendors=None` dropped | This branch runs only when `ctx.vendorset is None`, and then `ctx.tier` is `None` too, so the defaults are equal. |
| `_pend_16`, `_review_and_record_68`, `_run_236/254` | `verdict="pending"` dropped | `_result`'s default verdict is `"pending"`. |
| `_review_and_record_107/109` | `exist_ok=False` → `None` / dropped | `None` is falsy, and the default is `False`. |
| `_run_17/18` | `split("/", 1)` → `split("/")` / `rsplit` | `resolve_repo_slug` returns validated `owner/name` with exactly one `/` (S1a `_run_20`). |
| `_write_findings_12` | `repo_slug` → `None` in `_validate_entries` | `canonicalize_findings_ex` reads `repo_slug` only for `source_url`/`conflicts_with`. `build_entries` never emits those keys. **The coder confirms** this in `lib/merge_authority.py`. |
| `_fp8_6/9` | `json.dumps(..., default=str)` → `default=None` / dropped | Items come from `json` parsing (`extract_json_objects`), so every value is JSON-native, and `default` is never called. |

The coder confirms each proof against the fresh run's mutated line. A proof that does not match is re-bucketed to "killed" and reported. A proof is never forced to fit. The PR comment lists each candidate with its proof for the human's Q2 answer.

## 12. Test plan (named tests)

### 12.1 `tests/automation/test_overseer_second_review.py` (M)

- T19, updated: the result key set equals `osr.RESULT_KEYS`.
- T-OSR-30: a counted pending emits `pending_count` and `pending_last_reason` equal to the values written to the counter file.
- T-OSR-31: a reused record emits both keys null.
- T-OSR-32: a record owned by another uid reads as absent. Monkeypatch `os.geteuid` to a different value.
- T-OSR-33: a record at mode 0640 is absent; 0600 is present.
- T-OSR-34: a symlinked `records/` dir makes the record absent.
- T-OSR-35: a malformed `created_at` makes the record absent.
- T-OSR-36: a final record whose reason does not match its verdict is absent (one case per verdict).
- T-OSR-37: a final record with `hold_label_applied` non-null is absent, and a hold record with null is absent.
- T-OSR-38: a findings file at mode 0644 fails `_findings_shape_ok`.
- T-OSR-39: `sanitize` neutralizes `@user`, `](`, `![`, and leaves an email-style `a@b` unchanged only where the next character is outside the class.
- T-OSR-40: a fence-hidden codex heading (kills `_vendor_status_5/6/7`, `classify_run_207`).
- T-OSR-41: with `tempfile.tempdir` pointing at a nonexistent path, the write still succeeds, because the temp file is created in the record's own dir (kills `_atomic_write_text_16`, AR19).
- T-OSR-50: under an ASCII locale codec (`-X utf8=0`, `LC_ALL=C`, `PYTHONCOERCECLOCALE=0`), a non-ASCII `ensure_ascii=False` findings text is written intact (kills `_atomic_write_text_28`, AR22).
- T-OSR-42: `pinned_base` returns the merge-base in a real repo and `None` for a bad sha.
- T-OSR-43: a HIGH raise on file, then `write_raise(tier="MEDIUM")`, leaves the file at HIGH (kills `write_raise_44`).
- T-OSR-44: an aged `.tmp-*` file in `records/` is swept by the next record write (kills `_atomic_write_text_17`).
- T-OSR-45: a findings-validation failure logs exactly `findings file failed validation (<ExcType>); holding` (kills `_validate_entries_12/13`).
- T-OSR-46: a request_changes run with two vendors, mixed severities and 41 or more findings. The test asserts the exact findings-file `path`, `slug`, order, `sr-overflow` dropped count and `detail`. It then passes the file, with `reviewed_head` popped, through `merge_authority.canonicalize_findings_ex` (kills the 13 finding-content mutants of §11.3).
- T-OSR-47: a records dir at mode 0755 makes the next write return `pending state-write-failed`, and no vendor call is made (AR10).
- T-OSR-48: a mixed `request_changes` record (`vendors_run == ["codex"]`, `vendor_failures == ["vendor-timeout:agy"]`) is **present** to `load_record` (AR8).
- T-OSR-49: a `pending-stuck` hold, persisted and non-persisted, carries `pending_count >= 3` and `pending_last_reason` (AR5).
- T-INT-01..07: real `run_cmd` integration (§11.3).
  - 01: agy stub cwd/argv/stdin.
  - 02: codex stub at HIGH.
  - 03: timeout passes through.
  - 04: env is scrubbed.
  - 05: a git diff over the real range.
  - 06: findings file written and read back by `_findings_shape_ok`.
  - 07: the classifier call's cwd and the cleanup call's timeout are recorded by the stub.
- The existing tests that rewrite records with `write_text` keep mode 0600. The umask fixture pins 0o022.

### 12.2 `tests/automation/test_osr_phase.py` (A)

The helper is loaded via `importlib` as `bin.lib.osr_phase`.

| Test | Asserts |
|---|---|
| T-PH-01 | valid approve result → exact OSR line, regex-matching |
| T-PH-02 | each missing key and each extra key → `invalid-line` strike (parametrized over `RESULT_KEYS`) |
| T-PH-03 | pr mismatch → invalid-line |
| T-PH-04 | range ≠ `base..head`, range with null base → invalid-line |
| T-PH-05 | vendors/tier null mismatch → invalid-line; tier null renders `vendors=-` |
| T-PH-06 | findings_file on approve → invalid; outside runs/ (incl. `..` and symlink) → invalid |
| T-PH-07 | record null except pending-stuck → invalid |
| T-PH-08 | hold_label_applied typing → invalid when wrong |
| T-PH-09 | pending_count/last_reason presence rule; values surface in `count=`/`last_reason=` |
| T-PH-10 | rc 1, 2, 124, 137 → strike runner-failed, count increments 1→2; at 3 → `hold pending-stuck persisted=false`, `ACTION=label` |
| T-PH-11 | non-strike result deletes strike file; head change resets count |
| T-PH-12 | strike write failure (read-only dir) → `hold state-write-failed`, `ACTION=label` |
| T-PH-13 | strike file wrong mode/owner/symlink → treated count=0, WARN |
| T-PH-14 | `budget` RUN/DEFER arithmetic at boundaries |
| T-PH-15 | `order` puts deferred PRs first; `ingest` clears defer |
| T-PH-16 | `label-result` sets `label=applied|failed`; held PR renders `skipped-held label=-`; hold on already-labelled → `existing` |
| T-PH-17 | `render` output: header, one line per PR in order, terminator `---`; every line matches the §5.2 regex |
| T-PH-18 | stdout > 64 KiB, two lines, non-JSON, JSON array → invalid-line |
| T-PH-19 | `untrusted-checkout`, `runner-unbounded` strikes count to hold |
| T-PH-20 | drift: helper vocab literals == runner `HOLD_REASONS`, `PENDING_COUNTED`, `PENDING_UNCOUNTED`, `VENDORSETS`, `TIERS`, `RESULT_KEYS`, `FINAL_REASON_FOR_VERDICT` |
| T-PH-21 | runner `pending` with each of `lock-busy`, `state-write-failed`, `config-error`, `github-error`, `untrusted-checkout`, and a counted reason with null `pending_count` → strike; third → `hold pending-stuck count=3 last_reason=<r>`, `ACTION=label` (AR1, binding item 2) |
| T-PH-22 | runner `skipped-held`/`held-label` → no strike, no label; a reused hold on a held PR → `label=existing`, `ACTION=none` (AR3) |
| T-PH-23 | `budget`: `--uncached-ran 0` → `RUN` even when `E + P > B`; `--uncached-ran 1` and `E + P > B` → `CACHE_ONLY`; a `--cache-only` `pending budget` result → deferred, ordered first next call (AR6) |

### 12.3 `tests/automation/test_pr_review_resolution.py` (M)

Use `_make_submit_ctx`, `_make_submit_args` and `submit_preamble_mocks`. Extend the `get_pull` mock with `base.sha`, and write record fixtures through `osr._write_record`, or through the runner's own atomic writer, at 0600.

| Test | Asserts |
|---|---|
| T-G1c-01 | approve at MEDIUM with agy approve record → posts; `payload.second_review.verdict == "approve"` |
| T-G1c-02 | no record → exit 3 `second_review_record_missing` |
| T-G1c-03 | record base_sha ≠ merge-base → missing |
| T-G1c-04 | record agy-only, argv HIGH → `second_review_tier_raise`; `raise_written` true afterwards and the next runner `read_raise` returns HIGH |
| T-G1c-05 | raise file HIGH, argv MEDIUM, agy record → tier_raise |
| T-G1c-06 | invalid raise file → treated HIGH |
| T-G1c-07 | hold record → not_approved |
| T-G1c-08 | request_changes record → not_approved |
| T-G1c-09 | V=none: not-required accepted; approve record at none rejected |
| T-G1c-10 | approve with unresolved_findings=1 → not_approved |
| T-G1c-11 | approve with binary_files=1 → not_approved |
| T-G1c-12 | vendors_run ≠ V → not_approved |
| T-G1c-10r..12r | the same three approve records written to disk (no monkeypatch) → `second_review_record_missing` end to end (AR19) |
| T-G1c-13 | SAFE argv → LOW → requires not-required record |
| T-G1c-14 | head_lock held by another fd → `second_review_record_unverifiable` |
| T-G1c-15 | non-40-hex head or base → missing |
| T-G1c-16 | comment event → G1c not run, still gets a marker |
| T-G1c-17 | diag contains every §8.4 key with the record's values (kills field-drop on files_reviewed, vendor_failures, outfile, created_at, …) |
| T-G1c-18 | diag present on refusal too |
| T-MK-01 | approve body ends with marker after interim sign-off; fields equal the accepted record |
| T-MK-02 | comment with no record → `verdict=none tier=- vendors=-` |
| T-MK-03 | tier-null hold → `tier=- vendors=-` |
| T-MK-04 | interim marker regex still matches the body |
| T-MK-05 | body containing a `<!-- hos-overseer-check` line → exit 2 D-4 refusal |

The existing S1/S2 tests in this file that approve need a record fixture: add an autouse-off fixture `osr_approve_record` and apply it to them explicitly.

### 12.4 `tests/automation/test_pr_review_wrapper.py` (M)

The Harness at line 230 copies a minimal module set. Add `scripts/automation/lib/overseer_second_review.py` to it. GIT_STUB must return a merge-base. The roughly 16 approve tests get a record fixture written through the harness. Add T-WR-G1c-01, a wrapper-level refusal propagating exit 3 and the reason, and T-WR-MK-01, the marker present in the posted body.

### 12.5 `tests/automation/test_hos_cron.py` (M)

Use `CronEnv` at line 133. Fake `overseer_second_review` and `osr_phase` modules go into `self.repo`, as the existing fake modules do, and the real helper is copied when the test needs it. The gh stub's `mergeable_state` match is extended to emit `labels`.

| Test | Asserts |
|---|---|
| T-CR-01 | overseer role, actionable PRs → block injected after pre-filter `---`; header and terminator present |
| T-CR-02 | worker role → no phase |
| T-CR-03 | module absent → no block, stderr reason |
| T-CR-04 | no timeout/gtimeout on PATH → runner never called; `runner-unbounded` |
| T-CR-05 | runner exits 1 three cycles → third cycle `hold pending-stuck`, edit_issue stub called with `--add-label needs-human --app overseer` |
| T-CR-06 | runner sleeps past per-PR max → killed; strike |
| T-CR-07 | PR labelled needs-human → `skipped-held`, runner not called |
| T-CR-08 | edit_issue fails → `label=failed`, audit `cycle-osr-hold-label-failed` |
| T-CR-09 | mark-hold-label exit 3 with persisted=false → no WARN; with persisted=true → WARN |
| T-CR-10 | helper render emits a bad line → whole block phase-error and labels |
| T-CR-11 | budget exhausted → later PRs called `--cache-only`; an uncached PR renders `pending budget` and runs first next cycle |
| T-CR-12 | untrusted checkout (dirty tracked file) → no runner call, strike, audit event |
| T-CR-13 | `_LOCK_DIR` mtime advanced during phase (heartbeat) |
| T-CR-14 | `_OSR_PER_PR_MAX` clamped to `_lock_ceiling - 300` (3300 at the 3600 floor) with a WARN; a non-integer `SECOND_REVIEW_VENDOR_TIMEOUT` → `config-error` hold. The `< 300` branch is unreachable (AR19). |
| T-CR-15 | a fake `osr_phase.py` that exits 1 in `order` → the phase aborts, the prompt carries bash-rendered `pending phase-error` lines that match the §5.2 regex, **and the claude stub still runs**; third consecutive abort → `edit_issue.sh --add-label needs-human` per PR (AR7) |
| T-CR-16 | `mark-hold-label` is invoked with `--pr N --head <sha40> --applied true` exactly (AR2) |
| T-CR-17 | budget spent after the first uncached review → later PRs invoked with `--cache-only`, and a cached approve PR renders `verdict=approve` in the same cycle (AR6) |

## 13. Scoped mutation run (binding)

- **Where:** a scratch `git worktree` under `mktemp -d`, never in the clone. The `[tool.mutmut]` config is added uncommitted in the scratch tree only. The coder uses `.claudetmp/2357-s1a-mutation/scope_cfg.py` and `undecorate.py`.
- **Tool:** `scripts/oversight/.venv/bin/python -m mutmut` (mutmut 3.8).
- **source_paths:** `scripts/automation/lib/overseer_second_review.py`, `bin/lib/osr_phase.py` and `scripts/automation/pr_review_cli.py`. Mutants in `pr_review_cli.py` are scored only for G1c, the marker and D-4 code (functions touched by S1b).
- **Tests:** `test_overseer_second_review.py`, `test_osr_phase.py`, `test_pr_review_resolution.py` and `test_bounce_lock.py`, in-process only. The subprocess-based `test_hos_cron.py` and wrapper tests are excluded, because mutmut cannot see through a subprocess. Sanity check first: one hand-made mutant in `osr_phase.py` must be reported killed, which proves the `bin.lib.osr_phase` import path is the mutated copy.
- **Freshness:** `rm -rf mutants/` before the run, and again after any source or test change.
- **Measure:** score = killed / (killed + survived), excluding mutants marked equivalent per §11.5. `timeout` counts as killed and `suspicious` as survived. Use `score.py`.
- **Thresholds (all must hold):**
  - runner module ≥ 75%;
  - `osr_phase.py` ≥ 75%;
  - G1c, marker and D-4 functions in `pr_review_cli.py` ≥ 75%;
  - **every S1b-bucket member of the 146 is killed** (100%, no threshold).
- **Report:** a PR comment with:
  - a per-module table: total, killed, survived, timeout, equivalent, score;
  - the 146 table: triple → new id → status → test that killed it or the disposition;

  The PR does not merge with any S1b-bucket survivor, and it is not submitted before the human answers Q2.
- **Live check after merge (AR16), before S2.** Confirm from the first live overseer cycle that G1c accepted at least one approve, or refused one with a reason other than `second_review_record_unverifiable` or integrity failure. G1c runs inside the overseer model's sandboxed Bash. If the sandbox changes `geteuid()` or masks `.claudetmp/overseer-authority/`, every approve refuses. That fails closed, but it halts auto-merge. The worker records the observed outcome in the S2 TD.

## 14. Traceability

### 14.1 ADR items

| AD | Satisfied in |
|---|---|
| AD-1 phase placement, trusted checkout, per-call timeout form | §3.4, §6.1–6.3 |
| AD-2 (runner, S1a) | unchanged; §3.1 extends |
| AD-3 OSR line, header, terminator, null-record hold, mark-hold exit 3, pending ≤3, findings shape | §5, §6.4, §6.6, C2 |
| AD-4 marker | §10 |
| AD-5 prose | §3.5 |
| AD-6 test plan items 13–16 | §12.3 (13–14), §12.5 (15), §12.2 (16) |
| AD-7 tier = max(floor, declared, raise) | runner unchanged; G1c §8.2 step 2d |
| AD-8 (vendorsets, S1a) | `required_vendorset` reused, §8.2 |
| AD-9 G1c, P6, base pin, integrity, reasons, placement, required-check map | §7, §8, C6, C7 |
| AD-10 head carry | §9.1 (S1c) |
| AD-11 slicing, S1c contingency, interim prose | §2, §9.3, Q0 |
| AD-12 per-PR max, budget, heartbeat, strike location | §6.2–6.6, §4 |

### 14.2 Binding requirements

| # | Requirement | Section |
|---|---|---|
| B1 (AD-11 binding 1) | outer `timeout --kill-after=30 $_OSR_PER_PR_MAX` on every runner call; 124/137 → `runner-failed` | §6.3 step 4, §6.7 |
| B2 (AD-11 binding 2) | 3-strike bound on `runner-failed`, `lock-busy`, `state-write-failed`; counter outside `records/` | §4, §6.5, §6.6 (AR1) |
| B3 (AD-11 binding 3) | G1c base pin | §8.2 step 1-2b, G1c-7 |
| B4 (AD-11 binding 4) | record integrity before any record is consumed | §7, §3.1 (AR10) |
| B5 (AD-11 binding 5) | mention/link neutralising; `tier=-`/`vendors=-` regex; marker keyed off `tier: null` | §5.2, §5.4, §10 |
| B6 (AD-11 contingency) | S1c merges before S2; interim `review_worktree.sh --expect-sha` prose | §2.3, §9.3 (AR12) |
| B7 (AD-3 note C1, AD-9 note P6) | non-persisted hold rendered with count/last_reason; `max(--tier, read_raise, record.tier)`, invalid raise = HIGH | §5.2 (AR5), §8.2 step 2a-2d |
| H1 (human ruling) | 146 field-drop survivors handled in the S1b TD | §11 |
| H2 | each field read by a real S1b reader test | §11.3, §12 |
| H3 | scoped mutation run in the S1b PR showing them killed | §13 |
| R-FC | fail-closed everywhere; pending the only label-less path, bounded | §6.5, §6.6 |
| R-PR | ≤15 files, ≤10 commits | §2.2 |
| R-INT | record-integrity mechanism chosen with justification | §7.1 |
| R-MUT | ≥75% threshold and measurement | §13 |
| PR-7 (ADR PR item 7) | mention and link neutralization | §5.4, §9.1 |
| #2358 | overseer check marker | §10 |
| S1a §10 hand-offs | result-key consumer (§5.3), mark-hold-label consumer (§6.4), record API consumer (§8), counter surfacing (C3) | as listed |
| Codex items 1–10 (ADR) | 1 phase timeout §6.3; 2 unbounded runner §6.2-3; 3 untrusted checkout §6.2-6; 4 null-record hold §5.3-7; 5 pending bound §6.6; 6 tier raise §8.2-4; 7 mention injection §5.4; 8 forged marker §10.3; 9 base pin §8.2-1; 10 integrity §7 | as listed |

## 15. Startup-gap recovery and affected sign-offs (rewritten by the architect, AR15)

**Should this have been settled before S1a's code was written?** No.

- **C4 (record integrity).** ADR AD-9 assigns this to S1b in so many words: "The integrity check itself is S1b scope". S1a's part was codex `--sandbox read-only`. Implementing it in `load_record` is S1b doing its assigned work. It is not a correction of S1a.
- **C3 (`pending_count`/`pending_last_reason`, `RESULT_KEYS`).** This is an additive extension of the result line. The ADR correction note on AD-3 (rev 3) requires S1b to carry the non-persisted hold's outcome to the model. That is S1b's hand-off, recorded as such in TD-S1a §10.
- **AR8-AR10 (the `load_record` consistency and writer-side dir checks).** These are corrections to this draft, not to S1a.

**Affected sign-offs.** None are orphaned. S1a's code-reviewer, security-reviewer, reliability-reviewer and unit-test sign-offs on PR #2384 cover S1a's merged diff, and that diff is unchanged as history. Every function S1b modifies (`_read_json_dict`, `_findings_shape_ok`, `load_record`, `read_raise`, `sanitize`, `_Ctx`, `_count_pending_locked`, `_result`, `_result_from_record`, `_atomic_write_text`, `_review_and_record`) is in S1b's own diff, so S1b's review chain reviews it in full. Two items are superseded rather than re-reviewed: S1a's T19 key-set assertion, which T19 here replaces, and the S1a mutation-run dispositions for the 146, which §11 replaces per the human ruling. **No `startup-artifact-gap` issue is required**, and the coder does not open one.

## 16. Hand-off

**Architect: APPROVED_WITH_CHANGES (2026-11-18, iteration 1).** Q0, Q3 and Q4 are ruled, and Q1 is resolved as C. The coder may start from this text. **Q2 is the human's.** The worker escalates it with `escalate_to_human.sh`, and the S1b PR is not submitted until it is answered. ADR-2357 carries the matching correction note (file 14), which the architect added in this review.

## 17. Re-adoption ruling over #2385 (architect, 2026-11-24, AR28-AR32)

**Context.** HEAD 45fb8c59c merges origin/main into the approved S1b head 36a8abf54. Main now carries #2385 (PR #2433). Under #2385 ruling Q2 C, a PR where step 4d requires a lens never auto-merges. An AUTO_MERGE matrix result becomes step 6's PROPOSE_ONLY path instead: a `comment` verdict with Expected action APPROVE and a request to `HUMAN_REVIEWER`. Step 1a (`overseer_merge.sh on-human-approval`) then merges on the human's approval. S1b's step 4a OSR text never said that a non-approving OSR result ends the PR's handling, so a `pending` PR could run 4d and the matrix and reach that APPROVE request. The human would then approve and step 1a would merge, with no second review ever completed. G1c gates only `event == approve`, and AD-9 "Not covered" excludes step 1a by design. A `hold` would also get two verdicts. The code-reviewer finding (register, 2026-11-24) is upheld as MUST_FIX.

**AR28. Only `approve` or `not-required` continues.** Every other OSR outcome ends the PR's handling for the cycle once its step 4a action is done: `pending`, `skipped-held`, `hold`, `request_changes` (after its route), no block, `phase-error`, a missing line, and a line whose `head` is not the head under review. Nothing after it runs: no other step 4a check (the `request_changes` route already carries the REVIEW_CHAIN entries, per AD-3), and none of step 4c, step 4d, the pre-matrix gates, step 5 or step 6. One rule with no partial paths was chosen over letting the send-back gates (4a chain, 4c) run on a `pending` PR. Those gates never approve, so running them would be safe. But a partial path adds ordering cases, and delaying a send-back costs nothing in safety. The delay is bounded: counted reasons by `pending-stuck`, `budget` by the AD-12 progress rule. If a later step restarts the PR on a moved head (step 4d.1's file-count check, or `review_worktree.sh` exit 4), handling re-enters at step 4a. The new head has no OSR line, so it is `pending` and stops.

**AR29. Expected action APPROVE requires a covering OSR result.** This is a positive precondition, held in addition to AR28 as defence in depth. The overseer posts Expected action `APPROVE`, on any disposition, only when this cycle's OSR line for the exact head under review says `approve` or `not-required` **and** its `vendors` covers the tier step 4a uses. Any disposition includes PROPOSE_ONLY, and HUMAN_REQUIRED for a CRITICAL, CODEOWNERS or protected-surface PR. The tier step 4a uses is the validated tier, else `tier_floor`, else HIGH. Coverage means `agy` at MEDIUM and `agy+codex` at HIGH and CRITICAL, with `not-required` valid only below MEDIUM. The vendor clause closes a second gap, which AR28 alone leaves open. The OSR tier comes from the pre-model tier source (AD-7). Only G1c compares it with the model's `--tier`, and only on an `approve` event, so a PROPOSE_ONLY comment could otherwise recommend approval of a HIGH head that only agy reviewed. On a shortfall, the overseer takes step 6's HUMAN_REQUIRED (other reasons) path with Expected action `OTHER`, naming `second review tier shortfall`. That applies `needs-human`, so the next cycle sees `skipped-held` and nothing loops. No raise file is written on this path. The human decides.

**AR30. Prose is sufficient for S1b. The mechanical control is S1d (#2428), before S2.** After AR28 and AR29, the only way to merge a head without a completed second review is for a human to approve it without the overseer asking. AD-9 accepts that as a human decision. Before S2, the worker's own pre-check and incomplete-review-chain condition (b) still apply. But AR28 and AR29 are instruction-level, which is the same narration exposure as #1357. S2 retires the worker pre-check, and must not land on prose alone. **#2428 (S1d) gains a required item:** `pr_review_cli.py submit-verdict` applies G1c's record test to a `comment` event whose `--expected-action` is `APPROVE` (refusing with the same exit 3 and reasons, and writing the raise on a tier shortfall), and to `request-reviewer` on PROPOSE_ONLY. That change stays in the file G1c already lives in. Step 1a stays outside G1c, as AD-9 says. The worker records this on #2428. S1b adds no file and no slice.

**AR31. Verdicts on a stopping path carry no lens table.** Step 4d.6 says every verdict carries a `### Review lenses (INTERIM #2385)` table. A `hold` verdict posted under AR28 never reached step 4d. So it carries no table and states `Review lenses: NOT RUN — second review <verdict> (#2357)` in the "could not verify" clause. Step 4d.1's reuse check requires a table, so such a verdict is never reused as a lens record. That fails safe.

**AR32. Doc currency.** The §"Getting a PR's code locally (#2287)" non-zero-exit bullet carries the two exceptions the cron prompt already states. Step 4d.7 drops #2357 from its plug-in list, because S1b lands the second review before the model, in step 4a. The ADR AD-9 and AD-10 text is amended (ADR correction note dated 2026-11-24).

**Product boundary.** These rulings only withhold an approval request. They fall within accepted failure mode (2), "a review that has not finished yet leaves the PR unapproved until a later cycle", and (1) for the tier shortfall hold. They change no cost, retention, topology or operational obligation, so no new PM or human checkpoint is needed.

**Startup-gap recovery.** Should this have been settled before S1b was built? No. When the ADR and S1b were written and approved, AUTO_MERGE was the only path to an approval request on a clean PR, and it posts an `approve` event, which G1c gates. #2385 landed on main afterwards and changed that premise. This is a cross-change interaction caught at re-adoption, not a gap in the initial review. No `startup-artifact-gap` issue is required.

**Affected sign-offs.**
- **Stand:** the S1b code, test, mutation-run, prompt-fidelity and dep-mapper entries. Code and tests are byte-identical to 36a8abf54, and this ruling changes prose only.
- **Re-review the overseer.md and cron-prompt delta:** code-reviewer (closes its own MUST_FIX, SHOULD_FIX and SUGGESTION), security-reviewer (the approval-request path is security-relevant), and the cross-vendor second review on the delta.
- **Run:** the inner-loop tests, because static tests may anchor on overseer.md prose (first-occurrence anchors).
- **Superseded:** the architect's 2026-11-18 approval for step 4a's `pending` and `skipped-held` bullets and AD-10's "G1c guarantees" sentence. AR28-AR31 replace them.

**Architect: APPROVED_WITH_CHANGES (2026-11-24, re-adoption iteration 1).** The worker applies the exact overseer.md and cron-prompt text from the AR28 ruling reply, then runs the re-reviews above.
