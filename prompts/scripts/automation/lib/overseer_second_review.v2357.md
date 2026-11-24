# Prompt Artifact — overseer_second_review.py / run_second_review.sh --authority (#2357 S1a)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/overseer_second_review.py` (new), `scripts/run_second_review.sh` (`--authority` mode), `scripts/automation/lib/merge_authority.py` (`keyed_flock` extracted from `_bounce_lock`), `tests/automation/test_overseer_second_review.py` (new), `SCRIPTS-INDEX.md` (regenerated) |
| **Description** | Slice S1a of #2357: the overseer's own authority-mode cross-vendor second-review runner, its overseer-owned per-head record/cache with locking and atomic completion, and the reusable keyed lock. Inert — nothing calls it until S1b. |
| **Date** | 2026-11-16 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief (verbatim
except for whitespace and the Worker clone's absolute path, redacted to `<worker-clone>`
for the portability gate):

```
You are implementing slice S1a of GitHub issue #2357 in the HOS repo at
<worker-clone>, on the already-checked-out branch
worker-2357-overseer-own-second-review-261116012001-2455441. Do NOT create, switch,
stash, check out or reset branches. Do NOT edit .claude/agents/*.md, docs/, or the
prompt artifact. Do not file issues, post comments or change labels.

The binding design is docs/v0.7.0/TD-2357-S1a-overseer-second-review-runner.md
(architect-APPROVED, amendments A1-A8 included), under
docs/v0.7.0/ADR-2357-overseer-second-review.md. Read both in full before writing code.
Implement exactly what the TD specifies — no more, no less. If anything in the TD is
ambiguous or contradicts the code, stop and report the question rather than guessing.

Files you may touch (TD file list):
  1. scripts/run_second_review.sh            (add --authority mode; worker mode unchanged)
  2. scripts/automation/lib/overseer_second_review.py   (new)
  3. scripts/automation/lib/merge_authority.py           (keyed_flock extraction only;
                                                          _bounce_lock behaviour identical)
  4. tests/automation/test_overseer_second_review.py     (new; every numbered test in the TD)
  5. SCRIPTS-INDEX.md  (regenerate: bash scripts/framework/gen_scripts_index.sh — no --check)

Hard constraints:
- S1a is inert: nothing existing calls the new module. The worker's existing
  run_second_review.sh invocation (without --authority) must behave exactly as today.
- Tests inject runner/worktree/git; stub gh and vendor CLIs on PATH; no live vendor or
  network calls; all temp files under pytest tmp_path (the suite fails on leaked temp).
- Vendor text is untrusted data: sanitise per TD §6.2.
- Use scripts/oversight/.venv/bin/python for pytest/black/ruff.

When done:
- Run the TD's test command list plus: bash scripts/framework/run_tests_inner_loop.sh
- Run bash scripts/oversight/run_gates.sh on the changed files and fix every finding in
  touched files (including black formatting).
- Commit with this trailer block (one contiguous block, no blank lines inside it):

    Prompt-Artifact: prompts/scripts/automation/lib/overseer_second_review.v2357.md
    AI-Model: claude-opus-5-5
    AI-Risk: HIGH
    Supervised-by: ScottThurlow

    Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

- Report: files changed, test results (counts), gate results, and self-flag per
  AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS).
```

## Revision 3 (2026-11-17, re-adoption cycle)

The cross-vendor second review (agy, high, logic-error) found that TD §5.7 step 4 let the pending-stuck path return a stale under-tier or stale-base final record. technical-design wrote TD revision 3, the architect approved it (with ADR-2357 correction note C1), and the worker then dispatched the `coder` subagent with this brief (verbatim except for whitespace):

```
You are implementing a revision of slice S1a of GitHub issue #2357 in the HOS repo at <worker-clone>, on the already-checked-out branch worker-2357-overseer-own-second-review-s1a-261117060501-148083. Do NOT create, switch, stash, check out or reset branches. Do NOT edit .claude/agents/*.md, docs/, or prompts/. Do not file issues, post comments or change labels. Do not commit; the worker commits.

Implement exactly TD-2357-S1a revision 3 (docs/v0.7.0/TD-2357-S1a-overseer-second-review-runner.md, §0.3 rev-3 rows P1-P5, §5.7 step 4 branches a-d, §5.8 record-null rule, §5.10 no audit for the non-persisted hold, §7.2 find_records note), no more and no less. The architect approved rev 3; ADR-2357 carries the matching C1 note.

Code: scripts/automation/lib/overseer_second_review.py `_count_pending_locked` (currently ~1131-1160) and whatever it needs (e.g. `_result_from_record` / a result builder for the non-persisted hold with record, findings_file, hold_label_applied, tier and vendors null). Summary of the required behaviour:
- (a) requirement known (ctx.base and ctx.vendorset both set): `load_record(ctx.root, repo=ctx.slug, pr=ctx.pr, head_sha=ctx.head, base_sha=ctx.base, vendorset=ctx.vendorset)`; if it returns a record R9a would reuse (a final, or a binary-unreviewed hold), delete the counter and return it with reused=True, without rewriting it or writing an audit event. Requirement unknown: never return an existing record. Stop using find_records here.
- (b) target filename: ctx.vendorset if known, else agy+codex with tier null.
- (c) requirement unknown and a valid final exists at the agy+codex filename (any base): do not write; return a non-persisted `hold pending-stuck` result; keep the counter; no audit.
- (d) otherwise write the hold record (overwriting a stale-base final when the requirement is known), delete the counter, audit, return it.
- Invariant: the stuck path returns approve or not-required only through (a).

Tests: tests/automation/test_overseer_second_review.py. Update T12 (4th bullet) and T27 (4th bullet) and add T30a-e exactly as the TD specifies (stale lower vendorset after write_raise holds with the agy file byte-identical; stale base holds and replaces, incl. MEDIUM -agy variant; matching final returned unchanged with reused=true, counter deleted, no audit, plus request_changes / binary-unreviewed variants and base/vendorset mismatch controls; unknown-tier collision gives the unsaved hold with file byte-identical, count 3 then 4, mark-hold-label exits 3, plus R5 fetch-failed variant; unknown tier no collision writes -agy+codex with tier null, plus overwrite-existing-hold variant).

Run with scripts/oversight/.venv/bin/python -m pytest tests/automation/test_overseer_second_review.py -q, plus black --check and the repo's lint on the two files. Keep coverage of overseer_second_review.py at or above 92%. Self-flag per AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS) in your final report.
```

## Revision 3 addendum P6 (2026-11-17)

The final-range second review (codex, high, CWE-367) found that R7 read the raise file outside head_lock. technical-design wrote addendum P6, the architect approved it (with an ADR-2357 AD-9 correction note), and the worker then dispatched the `coder` subagent with this brief (verbatim except for whitespace). A follow-up hand-back: the coder also guarded the refresh against a None tier_sources for the test helper context.

```
You are implementing addendum P6 of TD-2357-S1a revision 3 (slice S1a of GitHub issue #2357) in the HOS repo at <worker-clone>, on the already-checked-out branch worker-2357-overseer-own-second-review-s1a-261117060501-148083 (HEAD 15d2a5f51). Do NOT create, switch, stash, check out or reset branches. Do NOT edit .claude/agents/*.md, docs/, or prompts/. Do not file issues, post comments or change labels. Do not commit; the worker commits.

Implement exactly the P6 addendum in docs/v0.7.0/TD-2357-S1a-overseer-second-review-runner.md (§0.3 row P6; §5.3 R7/R8 provisional wording and the new R9 step 0; §5.4 single reader `read_raise`; §5.7 step 1 refresh on the lock_held=False path; test T31a-e), no more and no less. It was architect-approved; ADR-2357 carries the matching AD-9 note. Read `git diff HEAD -- docs/` for the exact text.

Finding being fixed (codex, high, CWE-367, verified): in scripts/automation/lib/overseer_second_review.py, R7 `compute_tier` (~line 1453) reads the raise file outside `head_lock` (taken ~1459), while `write_raise` serializes on that lock, so a raise landing between them leaves a stale lower tier/vendorset for R9a reuse or the review.

Summary of the required behaviour (the TD governs):
- Add `read_raise(...) -> (r_tier, r_invalid)`, the only reader of the raise file. `compute_tier` uses it.
- Add `_refresh_raise_locked(ctx)`, the first action inside head_lock in R9 before R9a and any lookup, review or write. The candidate is HIGH if the file is invalid, r_tier if valid, None if absent. Only if the candidate is above ctx.tier: lift ctx.tier, recompute ctx.vendorset, set tier_sources["raise"] (for an invalid file: raise null, add "raise-invalid" once to defaulted). Never lower. No subprocess. Floor and declared are not re-read.
- §5.7: when `_count_pending` takes the lock itself (lock_held=False) and ctx.vendorset is set, run the refresh right after acquiring the lock and before the counter read, so step 4 uses the refreshed vendorset. Do not refresh when the tier is unknown, or when lock_held=True (R9 step 0 already did it).
- Tests in tests/automation/test_overseer_second_review.py: T31a-e exactly as the TD specifies, simulating the race by patching the module's head_lock to enter the real lock, run a hook that writes the raise with _atomic_write_json, and then yield, each with a no-hook control. Keep the existing tests passing (T4b, T11, T27 and T30 included).

Run scripts/oversight/.venv/bin/python -m pytest tests/automation/test_overseer_second_review.py -q, scripts/oversight/.venv/bin/python -m mypy scripts/automation/lib/overseer_second_review.py (it must be clean, with no casts or type: ignore), and black --check on both files. Keep coverage of overseer_second_review.py at or above 92%. Self-flag per AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS) in your final report.
```

## Slice S1b (2026-11-18): cron pre-model wiring + G1c

Generated files: `bin/hos-cron` (M), `bin/lib/osr_phase.py` (A), `scripts/automation/lib/overseer_second_review.py` (M), `scripts/automation/pr_review_cli.py` (M), `bootstrap/overseer-cron-prompt.md` (M), `docs/LABELS.md` (M), and the five test files named in the brief. Risk level: HIGH. Design: `docs/v0.7.0/TD-2357-S1b-overseer-second-review-wiring.md`.

The worker (top-level session) dispatched the `coder` subagent with this brief, verbatim:

~~~~
Implement slice **S1b of #2357** exactly as specified in `docs/v0.7.0/TD-2357-S1b-overseer-second-review-wiring.md` (architect APPROVED_WITH_CHANGES 2026-11-18; amendments AR1-AR16 in §0.1 are binding and override any earlier text they amend). Governing ADR: `docs/v0.7.0/ADR-2357-overseer-second-review.md` (including the 2026-11-18 correction note). Merged S1a design: `docs/v0.7.0/TD-2357-S1a-overseer-second-review-runner.md`.

Repo: `<worker-clone>`, branch `worker-2357-overseer-second-review-s1b-261118220502-2814304` (already checked out; do NOT create, switch, or stash branches; never run `git stash` or `git checkout`).

**Your files (TD §2.2 S1b list), and only these:**
- `bin/hos-cron` (M): the overseer pre-model OSR phase, per the TD (§3, §4, §6).
- `bin/lib/osr_phase.py` (A): stdlib-only, run with `python3 -I`.
- `scripts/automation/lib/overseer_second_review.py` (M): result-key extension, record integrity (§7.1/§7.2), writer-side mode enforcement (AR10), strike-relevant results.
- `scripts/automation/pr_review_cli.py` (M): G1c after G2, before G3, with the four reasons incl. `second_review_record_unverifiable` (Q4=A), `max(--tier, current raise via read_raise, record.tier)` with null-safe handling (AR12) and invalid raise ⇒ HIGH; base pin; #2358 marker (§10).
- `bootstrap/overseer-cron-prompt.md` (M): the one sentence / interim prose per TD §3.5 and §9.3.
- `docs/LABELS.md` (M): `hos-cron` as a `needs-human` writer.
- Tests: `tests/automation/test_hos_cron.py` (M), `tests/automation/test_osr_phase.py` (A), `tests/automation/test_overseer_second_review.py` (M), `tests/automation/test_pr_review_resolution.py` (M), `tests/automation/test_pr_review_wrapper.py` (M). Implement every named test in TD §12, including the field-reader tests in §11.3/§11.4 (T-OSR-43..49, T-INT-07, and the Q1=C route-path kills). Each field-drop mutant must be killed by a test that reads the field through a real S1b reader (phase, G1c, marker), per the human ruling, not by a bare assertion added only to kill it.

**Not yours:** `.claude/agents/overseer.md` (the top-level session edits it, per #1347; coder must not write agent definitions); the TD, the ADR, and the prompt artifact; `merge_authority_cli.py` / `lib/merge_authority.py` / `test_merge_authority_cli.py` (S1c). If the design is wrong or ambiguous, stop and report the question; do not improvise.

**Constraints:**
- Fail closed everywhere. `pending` is the only label-less path and it is bounded. Every runner call in the phase is wrapped in `timeout --kill-after=30`. The phase is isolated so that an abort never kills the cycle (AR7: subshell with `set +e`/`set -e`, never `||`).
- Never invoke `bin/hos-cron` for real. Tests exercise it only via the existing test harness and fixtures.
- Bash: one command per call, with no `&&`/`;`/pipes chaining. Redirect long test output to a file under `.claudetmp/2357-s1b/` and read it with Read. Example: `scripts/oversight/.venv/bin/python -m pytest tests/automation/test_osr_phase.py -q -p no:cacheprovider > .claudetmp/2357-s1b/t1.log 2>&1`.
- Run black/ruff/mypy on changed Python (`bash scripts/oversight/run_gates.sh <changed files>`) and keep it clean.
- Commit in at most 3 commits. Every message ends with exactly this one contiguous trailer block:

```
Prompt-Artifact: prompts/scripts/automation/lib/overseer_second_review.v2357.md
AI-Model: claude-opus-5-5
AI-Risk: HIGH
Supervised-by: ScottThurlow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

No closing keywords ("closes/fixes/resolves #N") in commit messages.

**Reply with:** commits (SHA + subject); per-file summary; test results for the five test files plus a full `bash scripts/framework/run_tests_inner_loop.sh` run (redirected to `.claudetmp/2357-s1b/inner.log`), with pass/fail counts; gate results; your self-flag (RISK/CONFIDENCE/BLAST RADIUS per AGENTS.md); every TD deviation or open question; and the list of the TD §11 proofs marked "the coder confirms", with your confirmation result for each.
~~~~
