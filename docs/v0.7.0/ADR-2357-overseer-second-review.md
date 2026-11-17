# ADR-2357: At MEDIUM and above, the overseer runs the cross-vendor second review itself, and its own result decides the PR

**Status:** PROPOSED (revision 2, with in-place corrections C1-C7 from technical-design and A1, A2, A5 and A6 from the architect's TD-2357-S1a review on 2026-11-16, all marked inline). It binds `technical-design` and `coder` once the human accepts this design PR. Revision 1 (2026-11-15) was never reviewed. Its AD-1 placement (inside the model's Bash tool, 270 s vendor cap) is withdrawn by the Q1 ruling.
**Date:** 2026-11-16 (rev 2), 2026-11-15 (rev 1)
**Author:** architect (autonomous worker cycle)
**Issue:** #2357, which is the first slice of epic #1709. **Milestone:** v0.7.0, bucket 1. **Risk tier: HIGH.** The change touches protected surface (`.claude/agents/overseer.md`, `bootstrap/**`, `bin/hos-cron`, `scripts/automation/**`), so the CODEOWNER gate applies. Edits to `.claude/agents/**` are made by the top-level session, never by `coder` (#1347).
**Product boundary:** the human ruled on 2026-11-15 and accepted two costs: roughly twice the agy and codex calls, and longer overseer cycles. The new user-visible failure modes are all forms of "the PR is not approved". (1) A vendor failure, an oversized diff, or a stuck review holds the PR with `needs-human` and a reason. Acceptance 3 requires this. (2) A review that has not finished yet leaves the PR unapproved until a later cycle. (3) An interactive overseer session cannot approve a PR unless a cron cycle, or a human running the runner, has recorded a review for that head (AD-9). (4) *(Added by the architect in TD-2357-S1a review, A1.)* A PR whose diff contains a binary file or a submodule pointer is never auto-approved. It is held `binary-unreviewed` for a human, because no vendor can read that content. That is item 9's "partial coverage is never an approval" applied to unreadable content. It has had zero occurrences on `main` since 2026-08-01. None of these changes cost, retention or topology beyond what the ruling accepted, so no further PM or human clearance is needed. The human reviews this PR at the CODEOWNER gate and can reject (3) or (4) there. **(4) is called out explicitly for that review.**

## Rulings (binding)

- **Q1 = B (ScottThurlow, 2026-11-15).** The overseer's second review runs in a **pre-model phase of `bin/hos-cron --role overseer`**, not in the model's Bash tool. The phase has no 600 s tool cap and keeps the normal `SECOND_REVIEW_VENDOR_TIMEOUT=900`.
- **Q2 = A.** This PR may edit the `.claude/settings.json` allowlist. **That edit is no longer needed and is dropped.** The model never calls the runner. `bin/hos-cron` calls it as an ordinary unsandboxed host process. The model only passes a findings file path to `bootstrap/merge_authority.sh route` and uses `bootstrap/edit_issue.sh` and `bootstrap/pr_review.sh`, all of which are already allowlisted.
- **Codex amendment items 1-10 (2026-11-15) are required.** The traceability table at the end maps each item to the AD that satisfies it.
- **#2358 addition.** The overseer's result must be countable from GitHub alone: a machine-readable marker in the verdict or bounce comment naming PR, head, tier, vendors, verdict and whether it caused a bounce (AD-4).
- **Not-adopted codex item, option A.** The evaluator, security and reliability reviewers stay worker-attested until #1815, #2327 and #1643. They are out of scope here.
- **Epic #1709.** This is the first slice. The storage layout, the record schema and the approval gate are keyed by a `check` name (`second-review`), so later #1709 slices add checks without replacing this one (AD-2, AD-9).

## 0. Verification findings

All line numbers are against this branch at `7df317440`.

- **VF-1 (diff from objects only).** `run_second_review.sh --diff A..B` builds the diff with `git diff "$DIFF_REF"` in cwd and records the range as full SHAs (`scripts/run_second_review.sh:297-304`). It needs only the commit objects. `bootstrap/review_worktree.sh --pr N --expect-sha <sha40>` fetches `refs/pull/N/head` into `FETCH_HEAD` and exits 4 if the head moved (header, lines 11-24). So the main checkout can review a PR without any local branch, and diff-only mode (SPEC-379, line 120) needs no PR tree on disk.
- **VF-2 (ledger can clear a finding).** `LEDGER_FILE=.claudetmp/second-review/step<STEP>-ledger.jsonl` (line 171). `aggregate --ledger` (line 1054) downgrades `request_changes` to `approve` when every blocking finding is ledgered (`scripts/oversight/second_review_logic.py:329`), and `process --ledger` (line 1084) treats ledgered fingerprints as not new. `--record` writes the ledger (lines 150, 183). Any ledger in authority mode lets the author's dispositions clear the authority's findings. `aggregate` accepts no `--ledger`. `process` requires `--ledger` (`scripts/oversight/validation_logic.py:792`) but treats a missing file as empty (`:423-435`).
- **VF-3 (silent pass and substitution paths).** `skipped` exits 0 (lines 233-249). At HIGH, codex stands in for a missing agy and runs one combined review (lines 255-257, 1002-1017). `--score` absent reads `.claudetmp/oversight/validators/summary.json` from cwd (line 196), and the validator digest also reads it from cwd (line 443). Either file may describe a different PR.
- **VF-4 (cwd config).** The runner reads `.env` (line 90, lower-only clamp) and **sources** `scripts/framework/config.sh` from cwd (line 382), which runs it as shell. With a PR tree as cwd, that is code execution of the author's file. With the overseer's main checkout as cwd, it is main's file.
- **VF-5 (side effect).** `create_finding_issues` (line 470) runs `gh issue create` for each high or critical finding and is called on every vendor path (lines 998, 1015, 1035).
- **VF-6 (oversize).** `vendor_invoke` refuses a prompt over the vendor ceiling (agy 180,000 bytes, `scripts/oversight/lib/vendor_invoke.sh:92`), recording `outcome_detail: prompt_too_large`, and never launches the binary (`:309-317`). The runner already greps for it (line 1171). It is a refusal, not a truncation.
- **VF-7 (timing).** Vendors run in sequence. agy can be invoked twice (one prose-reinforce retry, lines 766-790), so a HIGH run is at most 3 x 900 s plus overhead, about 2,800 s.
- **VF-8 (cron session cap and lock).** `HOS_CRON_MAX_SECONDS` wraps **only** the claude session (`bin/hos-cron:2342-2343`). Anything before line 2342 does not count against it. The overlap lock's staleness ceiling is `2 x HOS_CRON_MAX_SECONDS`, floored at 3,600 s (`:324-327`). It is measured from the lock directory's mtime (`:344-345`), and a contender reclaims at or above the ceiling regardless of PID liveness (`:370-373`). With this project's `hos_max_seconds=10800`, the ceiling is 21,600 s. With the default of 1,800 s, it is 3,600 s. One HIGH review (VF-7) plus a full claude session at the default cap would exceed that unless the holder refreshes the mtime.
- **VF-9 (trusted checkout).** After sync, `bin/hos-cron` fast-forwards the working tree only when HEAD is `main` (`:1924-1938`). Otherwise it moves `refs/heads/main` without touching the tree (`:1941`). "Run the tool from the main checkout" is trustworthy only when HEAD is `main`, HEAD equals `origin/main`, and tracked files are clean.
- **VF-10 (audit log is not overseer-owned).** Every role pushes `audit/log/**/*.json` to the unprotected `audit-log` branch, and a workflow commits those files to `main` (`bin/hos-cron:568-628`). The worker's audit records therefore arrive in the overseer's `audit/log/` on the next sync. An `overseer-second-review` event in `audit/log/` is **forgeable by the worker**. It can be evidence, never authority.
- **VF-11 (route re-reads the head).** `route` re-fetches the PR and takes `head_sha` from it (`scripts/automation/merge_authority_cli.py:1206-1207`). It pins that head again just before writing (`:1061-1069`, `:1384`). The argv surface deliberately has no `--head-sha` (`:188-195`, §3.4.0 Rule A). The findings file's top level must be exactly `{"findings": [...]}` (`scripts/automation/lib/merge_authority.py:1724-1729`). The CLI parses the JSON itself before canonicalizing it (`merge_authority_cli.py:1185-1203`).
- **VF-12 (approval is head-pinned).** `pr_review_cli.py submit-verdict` re-fetches the PR and posts with `commit_id = pre.head_sha` (`scripts/automation/pr_review_cli.py:747-904`). Refusal guards G0-G2 sit before the POST (`:792-880`). Branch protection sets `dismiss_stale_reviews: true` (`scripts/framework/setup_branch_protection.sh:171`), so an approval covers only the head it names. The wrapper already appends a code-owned marker and refuses a body that contains one (`pr_review_cli.py:934-946`).
- **VF-13 (tier inputs available without the model).** `scripts/oversight/change_classifier.py --tier-floor --base <sha> --head <sha>` re-derives a deterministic floor from git objects only (`:323-345`, `:670-676`, `:716`). The worker records its validated tier in each commit's `AI-Risk:` trailer (W-10). `run_validators.sh --diff` lists the changed names but scores the files **in cwd** (`scripts/oversight/run_validators.sh:73-85`, `:125-131`). In the main checkout that means main's copy, not the PR's, so it is not a valid pre-model tier source as is.
- **VF-14 (existing lock primitive).** `merge_authority._bounce_lock` is a kernel `flock` with a timeout and transient/deterministic classification. It is safe across sandbox PID namespaces (`merge_authority.py:2355-2432`; the range was corrected by TD-2357-S1a C1). Reuse it rather than writing a second one.

## AD-1: Placement. A pre-model phase in `bin/hos-cron --role overseer`

**Where.** It is a new block in `bin/hos-cron`, placed after the main-sync guards (`:1862-1941`) and the overseer branch-reap block (`:1781-1848`), before `# ── Cycle start` (`:2284`). The PR list is `_HOS_ACTIONABLE_PRS` from the existing pre-filter (`:1537-1596`).

**Trusted-checkout precondition (VF-9).** Before any PR is processed, the phase checks that `git symbolic-ref --short HEAD` is `main`, that `HEAD` equals `origin/main`, and that `git status --porcelain --untracked-files=no` is empty. If any check fails, no PR is reviewed. Every actionable PR gets `verdict=pending reason=untrusted-checkout`, and the phase writes the `cycle-osr-untrusted-checkout` audit event. Tools always run by absolute path from `$REPO_ROOT`, with `$REPO_ROOT` as cwd.

**Per PR.** The phase loops over the PRs in the committed script, not at an agent prompt. For each PR it does four things:

1. Run `_hos_refresh_token` (`:1095`), which does nothing while the token is young.
2. Refresh the lock heartbeat with `touch "$_LOCK_DIR"` (AD-12).
3. Run `<timeout> --kill-after=30 $_OSR_PER_PR_MAX python3 -m scripts.automation.lib.overseer_second_review run --pr <N> [--cache-only]` with cwd `$REPO_ROOT`.
4. Read exactly one JSON line from the runner's stdout. Validate it, then append one context line (AD-3).

A non-zero exit, a timeout (124 or 137), or output that is not valid JSON gives `verdict=pending reason=runner-failed`. The phase never aborts the cycle. The model still runs, so merges on human approval and other duties proceed.

**After the loop.** The phase applies `needs-human` mechanically to every `hold` result (AD-3), refreshes the heartbeat and the token one last time, and hands the context block to the prompt injection at `:2494` (AD-3).

**The runner** is `scripts/automation/lib/overseer_second_review.py` with a `main()`. It is not a bootstrap wrapper, because no model calls it. It owns everything specific to one PR:

1. Fetch the PR with `scripts/automation/lib/github.py`: head SHA, base ref, labels, author.
2. Skip held PRs. If the PR carries `needs-human` or `hos-halt`, return the stored `hold` state if one exists, else `verdict=skipped-held`. Make no vendor call. This is what stops a held PR from re-spending vendor calls every cycle.
3. If the head commit or the PR's `base.sha` commit is not in the local object store, run `bootstrap/review_worktree.sh --pr N --expect-sha <head>` now to fetch them (step 6's mapping applies).
4. Set `base = git merge-base <pr.base.sha> <head>`. Compute the tier (AD-7). Look up the record under the per-key lock (AD-2). On a final hit, return it with `reused: true`. Below MEDIUM, write a `not-required` record and return.
5. With `--cache-only`, stop here and return `pending reason=budget`.
6. If step 3 did not run it, run `bootstrap/review_worktree.sh --pr N --expect-sha <head>` now, which pins the head right before the review. Exit 4 gives `pending reason=head-moved`. Any other non-zero exit gives `pending reason=fetch-failed`.
7. (Merged into step 4.)
8. Run `scripts/run_second_review.sh --authority --out-dir <run-dir> --step pr<N> --diff <base>..<head> --tier <T> --score 0` (AD-8).

*Correction (TD-2357-S1a C3, C4, C5).* Revision 2 computed the tier and the cache key before the fetch and the merge-base, but both need the head objects and `base`. It used `origin/<base-ref>`, which is stale for any base other than `main` and widens the diff past GitHub's file list. It also omitted `--step`, which `run_second_review.sh` requires (`:165-168`). Steps 3-8 above replace that order. A cache hit on a head whose objects are already local makes no fetch.
9. Classify the result, write the findings file and the record atomically, and write the audit evidence event (AD-2, AD-3).
10. Always run `review_worktree.sh --cleanup --pr N`.

## AD-2: The overseer's own state. Records, cache and lock

**Location.** Everything goes under `$REPO_ROOT/.claudetmp/overseer-authority/second-review/` in the **overseer's** clone. That location is persistent working state: never reaped, never committed, never synced (CLAUDE.md "Temp and working-state locations" rule 2). It is not under `audit/log/` (VF-10) and not under `.claudetmp/second-review/`, which is the worker-style runner's directory and holds ledgers (VF-2). The worker cannot write it because it lives in a different clone, outside the worker sandbox's allowed paths. The design relies on that boundary and states it here.

```
records/pr<N>-<head40>-<vendorset>.json   final or hold record (vendorset = "agy" | "agy+codex" | "none")
runs/pr<N>-<head12>-<UTC-ts>/             run_second_review out-dir: raw report, findings.json
```

**Record schema (v1):**

```
{schema: 1, check: "second-review", repo, pr, head_sha, base_sha, range, tier, tier_sources,
 vendors_required, vendors_run, status: "final"|"hold", verdict, reason, unresolved_findings,
 findings_file, outfile, files_reviewed, binary_files, hold_label_applied, vendor_failures, created_at}
```

- **Key.** The key is repo, PR, base, head and the required vendor set. Repo and base are verified fields inside the record. The filename carries PR, head and vendor set, because one clone serves one repo and the base is almost always a function of the head. *(Corrected by architect, TD-2357-S1a A5. Under C4, base is `merge-base(pr.base.sha, head)`. It can change for an unchanged head when the base branch absorbs some of the head's ancestors, for example when a stacked PR's parent merges. The lookup therefore always passes `base_sha`. A mismatch is treated as absent, and the re-review atomically replaces the record at the same filename, which now covers GitHub's narrower diff.)*
- **Locking.** *(Corrected by architect, TD-2357-S1a A6: the lock key is `(repo, pr, head)`, coarser than the record key, so `mark-hold-label`, the pending counter, raise writes and the pending-stuck hold, none of which know base or vendor set, share one lock with the record write.)* The runner holds `keyed_flock("osr", <repo, pr, head>)` from lookup through record write, so a cron cycle and an interactive human run cannot review the same key twice. `keyed_flock` is `_bounce_lock`'s body, extracted in `merge_authority.py` with `_bounce_lock` delegating to it and its behavior unchanged (VF-14). A lock timeout gives `pending reason=lock-busy`.
- **Atomic completion.** Write the record to `records/.tmp-<random>` in the same directory, `fsync` it, then `os.replace` it to its final name. A reader that finds invalid JSON, `schema != 1`, or a field mismatch treats the file as absent. A crash before the replace leaves no record, so the next cycle re-runs.
- **What is reusable.** Only `status: "final"` records, with verdict `approve`, `request_changes` or `not-required`, which are completed judgments, plus one **deterministic hold**, `binary-unreviewed` (TD-2357-S1a A1). A re-run on the same head and base cannot change it and would cost a full vendor call.
- **What is never final.** Operational failures: vendor missing or unavailable, timeout, vendor error, `unparseable`, `prompt_not_consumed`, `prompt_too_large`, fetch or lock failures, and `head-moved`. They are never stored as `final`. A `hold` record exists only to suppress re-runs while the PR carries `needs-human` (AD-1 step 2). Once a human removes the label, the next cycle re-runs the review. So item 4's "retryable" holds, and the retry is paced by a human action rather than running every 20 minutes against a vendor that is down.
- **Tier rise.** A rise on the same head (MEDIUM to HIGH) changes the vendor set, so it misses the cache and re-runs. A fall never reuses a narrower record for a higher tier.
- **Evidence.** Every `final` or `hold` result also writes an `overseer-second-review` event to `audit/log/` with `audit_log.write_event`. Nothing in this design reads it back (VF-10).

## AD-3: Mapping a result to an action, and the hand-off to the model

**Context block.** The phase prepends a block after the existing `HOS_ACTIONABLE_PRS` preamble (`bin/hos-cron:2494-2498`), with one line per actionable PR:

```
[hos-cron overseer second review (#2357)]
OSR pr=#<N> head=<sha40> base=<sha40|-> tier=<LOW|MEDIUM|HIGH|CRITICAL> vendors=<agy|agy+codex|none> verdict=<approve|request_changes|not-required|hold|pending|skipped-held> reason=<token> findings_file=<abs path|-> reused=<true|false>
---
```

Every field comes from code and is a closed enum, a 40-hex SHA, or a path under the record directory. **No vendor text and no PR text** goes into the block. Before injection, each line must match an anchored regex, and the `reason` token must match `^[a-z0-9:-]{1,64}$`. A line that fails becomes `verdict=pending reason=invalid-line`, which is the same CWE-117 guard the branch-reap block uses (`:1800-1807`).

**Actions the model takes:**

| Line | Action |
|---|---|
| `approve` (the runner emits it only when `unresolved_findings == 0` and every required vendor ran) | The second-review part of step 4a passes. Continue. |
| `not-required` | Tier below MEDIUM. Continue. |
| `request_changes` (includes a vendor `approve` with unresolved findings, which the runner normalizes) | Bounce through `bash bootstrap/merge_authority.sh route --app overseer --pr <N> --step <N> --findings-file <findings_file>`. If conditions (c)/(d) of the interim rule also hold on this head, write one combined file that copies the runner's entries and its `reviewed_head` verbatim and adds the `REVIEW_CHAIN` entries, so the head spends one bounce. Payload and label handling follow the existing step 4a text: every exit leaves `needs-ai` or `needs-human` (AD-10). |
| `hold` | `hos-cron` has already applied `needs-human`. The model posts a `comment` verdict with disposition `HUMAN_REQUIRED` that names the reason. If the reason is `hold_label_applied=false`, the model applies `needs-human` itself. Never approve. |
| `pending` or `skipped-held`, a PR with no `OSR` line, or a head that differs from the line's head when the model looks | Do not approve. Post nothing and change no label, as with the existing transient path: re-evaluate next cycle. Never act on a newer head with an older result. |

**Hold reasons**, all closed tokens: `vendor-unavailable:<v>`, `vendor-error:<v>`, `vendor-timeout:<v>`, `vendor-missing:<v>` (a required section is `SKIPPED` or absent), `unparseable`, `prompt-not-consumed:<v>`, `diff-too-large`, `pending-stuck`, and, added by TD-2357-S1a, `empty-diff`, `review-inconsistent` and `binary-unreviewed`. The full closed vocabulary is TD-2357-S1a §5.6.

**Mixed results (TD-2357-S1a A2).** If any required vendor's result is `request_changes`, the result is `request_changes`, even when another vendor failed. The head is unmergeable either way, and the bounce gives the worker concrete work. The failures are kept in the record's `vendor_failures`, and the next head is reviewed again by every tier vendor. **More than one section for one vendor** gives `review-inconsistent`, because vendor stdout can close its own fence and forge a section heading.

**Mechanical `needs-human` on hold.** After the loop, `hos-cron` runs `bash bootstrap/edit_issue.sh --number <N> --add-label needs-human --app overseer` for each new `hold` and writes `hold_label_applied` into the record. If that call fails, it logs a WARN and writes `cycle-osr-hold-label-failed`. The model then applies the label (table above). This makes item 6 mechanical for the pre-model path. The runner itself still has no GitHub side effects (item 7).

> *Correction note (TD-2357-S1a rev 3, architect 2026-11-17).* A `hold` result can carry `record: null`: this is the non-persisted `pending-stuck` hold of TD-2357-S1a §5.7 step 4c. `hos-cron` applies `needs-human` to it as to any new hold. There is no record to write `hold_label_applied` into, so `mark-hold-label` exiting 3 is expected for that line. The model's fallback ("applies `needs-human` itself") is triggered by the `edit_issue.sh` call failing (the `cycle-osr-hold-label-failed` WARN), not by a record field. S1b must carry that outcome to the model in the context block, because the `OSR` line has no `hold_label_applied` field.

**Bounded pending.** The runner counts consecutive `pending` results per `(pr, head)` in `records/pr<N>-<head40>-pending.json`. On the third, it returns `hold reason=pending-stuck`, which is then labelled as above. A PR therefore cannot sit silently unapproved forever.

**Findings file**, written by the runner, never by the model:

```
{"findings":[{"class":"REVIEW_FINDING","slug":"sr-<vendor>-<fp8>","summary":"overseer second review (<vendor>): <severity> finding","detail":"<sanitized>","path":<changed file|null>}],
 "reviewed_head":"<sha40>"}
```

- **One entry per blocking finding.** A blocking finding is high or critical, from `findings` or `attacks`, extracted with `validation_logic.extract_json_objects` and `second_review_logic._split_sections`. Do not write a new parser.
- **Stable keys.** `fp8` is the first 8 hex characters of `sha256(validation_logic.fingerprint(item))`, so the same head gives the same keys. *(Corrected by TD-2357-S1a C2: `fingerprint()` returns a JSON string, not hex.)*
- **No extractable finding.** A vendor whose verdict is `request_changes` but which yields no blocking finding (for example a prose verdict) gets one entry, `sr-<vendor>-verdict`.
- **Entry cap.** At most 40 `sr-` entries are written, which leaves room for the 6 `REVIEW_CHAIN` roles within `FINDINGS_MAX = 50`. Any overflow becomes one `sr-overflow` entry that gives the dropped count.
- **`summary` is code-templated.**
- **Sanitizing `detail`.** `detail` is collapsed to one line and cut to 2,000 characters. A leading `/hos` is stripped. `<!--` and `-->` are replaced, so vendor text cannot forge the AD-4 marker inside a bounce comment.
- **`path`** is kept only when it is in `git diff --name-only <range>`.
- **Untrusted content.** The vendor reviewed diff content that the author influences. Its text is data, never instructions.

## AD-4: Recording the result, and the #2358 marker

Code appends the marker, never the model. It has one form:

```
<!-- hos-overseer-check v=1 check=second-review pr=<N> head=<sha40> tier=<T> vendors=<set> verdict=<v> bounced=<true|false> -->
```

- **On every overseer verdict.** `pr_review_cli.py submit-verdict` with `--app overseer`, for both the `approve` and `comment` events, appends the marker for the record on `pre.head_sha`. It writes `verdict=none` if no record exists, and `bounced=false`. As with D-4 (VF-12), it refuses a body in which any line opens with `<!-- hos-overseer-check`.
- **On every bounce comment.** `record_pr_bounce` gains an optional `marker` argument. `merge_authority_cli._write_bounce` fills it from the record for the live head. It sets `bounced=true` when the bounce includes any `sr-` entry, and `bounced=false` when the bounce is for other reasons, such as `REVIEW_CHAIN` only.
- **Counting.** #2358 counts distinct `(pr, head)` markers on comments and reviews authored by the overseer App login. The worker cannot post as that login, and vendor text cannot inject a marker (AD-3 sanitizing).
- **Local evidence.** The record and the `overseer-second-review` audit event carry the same fields plus `range`, `outfile` and `files_reviewed`.

## AD-5: Prose edits

**S1b (additive; the interim #2339 rule is unchanged):**

- **`overseer.md` step 4a** gets a new paragraph, **"Overseer-run second review (#2357)"**, before "Incomplete review chain". It states the AD-3 table, that the `OSR` line is the only second-review authority, and that the PR body's second-review claim is informational. It also states that `pending`, a missing line, or a head mismatch is never an approval, and that `pr_review.sh` refuses an approval without a record (AD-9). It does not tell the model to run any second-review command.
- **`overseer-cron-prompt.md`**, near line 52 (the preamble description), gets one sentence: "The `[hos-cron overseer second review]` block lists the overseer's own second-review result per PR. Act on it per `overseer.md` step 4a "Overseer-run second review": `request_changes` → route with its `findings_file`; `hold` → `HUMAN_REQUIRED` comment verdict; `pending`, `skipped-held`, a missing line or a different head → do not approve, re-evaluate next cycle."
- **`.claude/settings.json`:** no change (see the Q2 ruling).

**S2 (amendment item 10). It lands only after S1b is merged and one live cycle has written records:**

- **Condition (a)** gains "other than the second review" after "a role the tier requires".
- **Condition (b)** becomes "(b) *second review:* see "Overseer-run second review (#2357)". The overseer's own result is the authority. The PR body is not consulted."
- **The `REVIEW_CHAIN` slug guidance** drops the `second-review*` sentence. The slugs stay in `REVIEW_CHAIN_ROLES` (`merge_authority.py:1417-1424`) so legacy bounce records still parse.
- **The "Interim status" line** changes to "caught only by conditions (c) and (d)".
- **`overseer-cron-prompt.md:70`:** remove "name no second review or", "name no agy or no codex second review, or", and the `second-review` slug sentence.
- **Ordering.** Until S2 lands, a worker that skips its own pre-check still bounces under (b). That is today's behavior, never weaker. #2358's experiment of turning the worker's run off needs S2 first.

## AD-6: Test plan

Tests inject the runner, the worktree, git, GitHub reads and the clock. **No live vendor calls**: vendors are stub executables on `PATH` that print canned envelopes.

**S1a, in `tests/automation/test_overseer_second_review.py`:**

1. **Acceptance 1.** A `request_changes` report produces a findings file that `merge_authority.canonicalize_findings_ex`, the real parser, accepts once `reviewed_head` is popped. The PR body is a fixture that claims an agy approve and is never read.
2. **Acceptance 2.** The runner has no code path that reads the PR body. A test asserts that the GitHub fake's `body` field is never accessed.
3. **Acceptance 3: holds.** Each of these gives `hold` with the expected reason, writes no `final` record, and calls the runner again on the next call after the label is cleared: vendor missing at MEDIUM; agy missing at HIGH (no codex substitution); a vendor timeout; an `error` header; `unparseable`; `prompt_too_large`; `prompt_not_consumed`; a required section `SKIPPED`.
4. **Acceptance 4: cache.** A second call on the same head after `approve` or `request_changes` makes zero runner and worktree calls and returns `reused: true`. A tier rise on the same head re-runs. Two concurrent calls on one key make one vendor run, using real `flock` and two processes. A record truncated mid-write is treated as absent.
5. **Normalizing.** An `approve` with `unresolved_findings > 0` becomes `request_changes`.
6. **SHAs.** `range`, `head_sha` and `base_sha` are 40-character SHAs and equal `merge-base..head`.
7. **Ledger isolation (item 1).** A worker-style ledger seeded at `.claudetmp/second-review/step*-ledger.jsonl`, plus one in the run directory, with the finding's fingerprint as `fixed`, does not change the verdict. Authority mode refuses `--record` and `--reset`. The `process` ledger path does not exist before or after the run.
8. **Authority mode (items 2, 3, 7, 8).** `--authority` without `--out-dir`, without both SHAs in `--diff`, or with a tier below MEDIUM is a usage error. A stub `gh` on `PATH` is never invoked. No file outside `--out-dir` is written. The prompt captured by the stub vendor contains no validator digest and nothing from `.claudetmp/`.
9. **Sanitizing.** `detail` has no newline, no leading `/hos`, no `<!--` or `-->`, and at most 2,000 characters. `path` is nulled outside the changed set. The overflow entry appears at 41 or more findings.
10. **Head moved.** Worktree exit 4 gives `pending reason=head-moved`, which is never final. Cleanup runs on every exit path.
11. **Tier (AD-7).** `max(floor, trailer, raise)`. A classifier error gives HIGH. No parseable `AI-Risk` gives HIGH.
12. **Pending counter.** The third consecutive `pending` on one head gives `hold reason=pending-stuck`.

**S1b:**

13. **`tests/automation/test_hos_cron.py`, the phase.** It uses the file's existing stub harness, with the runner stubbed as a script on the module path:
    - An untrusted checkout (detached HEAD, a dirty tree, or HEAD not equal to `origin/main`) gives every PR `pending reason=untrusted-checkout` and makes no runner call.
    - A runner crash, exit 124, exit 137 or invalid JSON gives `pending reason=runner-failed`, and the claude session still runs. Every runner invocation is under `timeout --kill-after=30 $_OSR_PER_PR_MAX` (AD-12).
    - The third consecutive `runner-failed`, `lock-busy` or `state-write-failed` on one head gives `hold` and one `needs-human` call. With `records/` unwritable, `state-write-failed` still reaches a hold (AD-12).
    - A pre-tier pending line with `tier=-` and `vendors=-` passes the regex.
    - Vendor `detail` containing `@user`, `[x](url)` or `![x](url)` is neutralised in every posted body.
    - The block lines in the prompt match the regex, and an injected line containing `\n` or vendor text is replaced with `invalid-line`.
    - The lock dir mtime is refreshed before each PR and before claude starts.
    - The budget is exhausted after the first uncached review, so later PRs run `--cache-only`.
    - Each `hold` produces exactly one `edit_issue.sh --add-label needs-human` call.
    - The `timeout` wrapper on claude is unchanged.
14. **`tests/automation/test_pr_review_resolution.py`, G1c and the marker:**
    - An approve with no record, a `hold` record, a `request_changes` record, a record for a different head, a record missing a vendor for `max(argv tier, record tier)`, or a corrupt record gives exit 3 with the expected `refusal_reason`.
    - A clean record gives the POST.
    - A record whose `base_sha` differs from `merge-base(pre.base.sha, pre.head_sha)` (a retargeted base) gives `second_review_record_missing` (AD-9 base pin).
    - A record that fails the integrity check (wrong owner, group- or world-writable, or a bad HMAC) is treated as absent (AD-9).
    - A marker for a pre-tier `pending-stuck` hold carries `tier=-` and `vendors=-`, never a derived vendor requirement.
    - A tier rise writes the raise file.
    - The marker is appended on both events, and a body that contains the marker is refused.
    - Existing approve cases get a fixture that writes a clean record.
15. **`tests/automation/test_pr_review_wrapper.py`.** Existing approve cases get the same record fixture.
16. **`tests/automation/test_merge_authority_cli.py`, route head carry (AD-10):**
    - A mismatched `reviewed_head` gives a `head_moved` transient failure and writes nothing.
    - An `sr-` entry without `reviewed_head` gives `findings_file_invalid`.
    - A matching `reviewed_head` bounces, and the comment carries the marker with `bounced=true`.
    - A `REVIEW_CHAIN`-only bounce on a head with a record carries `bounced=false`.

**S2:**

17. **`tests/automation/test_route_pr.py` doc anchors.** Condition (b) no longer contains "names no second review", and both prose files name "Overseer-run second review (#2357)".

## AD-7: Tier source before the model runs

The tier is `max(floor, declared, raise)`. All three inputs are cheap and read no PR code:

- **floor:** `change_classifier.py --tier-floor --base <base> --head <head>`, run from the main checkout against git objects (VF-13). This is the overseer's own independent input.
- **declared:** the highest `AI-Risk:` trailer over `git log <base>..<head>`. It can only raise the tier. If no commit has a parseable value, it counts as HIGH: a worker PR always carries the trailer (W-10), so its absence is itself a signal.
- **raise:** `records/pr<N>-<head40>-raise.json`, written by G1c when the model's validated tier, its `--tier` argument from its own validator run, exceeds the recorded tier (AD-9). The next cycle re-reviews at the higher tier, so the gap closes in one cycle.
- **If undeterminable:** a classifier error or a git error gives HIGH.

`run_validators.sh` is **not** run before the model. It scores files in cwd (VF-13) and writes the shared `.claudetmp/oversight/validators/` directory. Fixing that is #1427's job, and the raise loop covers the gap until then. The worker's tier is never the only input. It can raise the tier and never lower it.

## AD-8: `run_second_review.sh --authority`

The flag is new, and the default path (the worker) is unchanged byte for byte. `--authority` requires `--out-dir <abs path>`, `--diff <sha40>..<sha40>`, `--tier MEDIUM|HIGH|CRITICAL` and `--score`. In authority mode the script:

- **Output paths.** `OUT_DIR` is `--out-dir`. The script writes nothing to `.claudetmp/second-review/`, and the skip sentinel path never runs.
- **No ledger (item 1).** It calls `aggregate` with no `--ledger`, and `process` with `--ledger <out-dir>/no-ledger.jsonl`, which is asserted absent first. It refuses `--record` and `--reset`.
- **No substitution (item 2).** It runs vendor selection from the tier alone, with `--score 0` from the runner. It checks every required vendor's availability **before** any call. If one is missing, it writes `verdict: error` and `reason: vendor-unavailable:<v>` to the header and exits 1, which matches every other `error` exit. *(Corrected by TD-2357-S1a C6; the runner reads the header, not the exit code.)* The codex fallback branch (lines 1002-1017) is unreachable.
- **No side effects (item 7).** It never calls `create_finding_issues`.
- **No cwd inputs (items 3, 8).** It reads no validator `summary.json` and leaves the validator digest out of the prompt. It records `validator_digest: omitted` in the header. `.env` and `config.sh` still come from cwd, which the runner guarantees is the trusted main checkout (AD-1, VF-4, VF-9). The spec context is main's `SPEC_FILE`.
- **Whole diff (item 9).** It builds the diff with `git -c core.attributesFile=/dev/null diff --no-ext-diff --no-textconv <range>`, so user-level attributes cannot hide a file (the worker's chunking workaround). It records `files_reviewed` and `binary_files` from `--numstat`, with gitlinks from `--raw` counted as binary. An otherwise-clean approve with `binary_files > 0` is `hold binary-unreviewed` (TD-2357-S1a A1). An oversized prompt is refused by `vendor_invoke` (VF-6), and the runner maps that to `hold reason=diff-too-large`. **Batching with recorded coverage is deferred to a later #1709 slice.** Partial coverage is never an approval.

## AD-9: Mechanical approval gate (G1c)

`pr_review_cli.py submit-verdict --app overseer --event approve` refuses with exit 3 **unless** the record at `<repo_root>/.claudetmp/overseer-authority/second-review/records/` for `(repo, pr, pre.head_sha)` exists, parses, has `status: final`, matches repo and head, and passes one of these two tests:

- `verdict == "not-required"`, and both the record tier and the `--tier` argument are below MEDIUM.
- `verdict == "approve"`, `unresolved_findings == 0`, and `vendors_run` covers the vendors required by `max(--tier, record.tier)`.

**Base pin (binding, S1a review architect SF-3).** G1c also requires `record.base_sha == merge-base(pre.base.sha, pre.head_sha)`. It calls `load_record` with that `base_sha` for each candidate vendor set. A base retarget on an unchanged head therefore cannot reuse a record that reviewed a different diff. A mismatch counts as `second_review_record_missing`.

> *Correction note (TD-2357-S1a rev 3 addendum P6, architect 2026-11-17).* Wherever this ADR says `max(--tier, record.tier)` (the two tests above, and test 14's "a record missing a vendor for `max(argv tier, record tier)`"), read it as `max(--tier, current raise, record.tier)`. The current raise is the raise file for `(repo, pr, head)` read at approval time through the runner's single reader `read_raise`, and a present but invalid raise counts as HIGH. The runner honors every raise committed before its locked section (TD-2357-S1a R9 step 0). A raise committed after the runner releases `head_lock` is the next run's input, so G1c must not trust the record's own tier alone. The `not-required` test therefore also requires the current raise to be absent or below MEDIUM. Test 14 gains one case: a valid `agy` approve for MEDIUM plus a HIGH raise file gives exit 3 (`second_review_tier_raise` or `second_review_record_missing`), and the same applies with an invalid raise file. This only clarifies the tier inputs; it changes no decision.

**Record integrity (binding, S1a review security SF-1).** Before G1c or the phase consumes any record, S1b adds an integrity check: either an ownership and mode check (owner is the overseer uid, no group or other write on the file and on `records/`), or an HMAC with an overseer-held key. A record that fails it is treated as absent. S1a's part is codex `--sandbox read-only` in authority mode, so a vendor cannot write the record directory. The integrity check itself is S1b scope.

**Refusal reasons:**

| Reason | When |
|---|---|
| `second_review_record_missing` | No usable record for this head. |
| `second_review_not_approved` | The record is a hold or `request_changes`. |
| `second_review_tier_raise` | The `--tier` argument needs more vendors than the record has. G1c also writes the raise file (AD-7). |

**Placement.** G1c sits after G2 and before G3 (`pr_review_cli.py:865-904`), so a refusal never POSTs.

**What it secures.** The approval is pinned to `pre.head_sha` (VF-12) and stale approvals are dismissed. So **head reviewed = head approved = head merged**. A pre-model crash, a missing line, or a model that ignores the block can never produce an approval. That makes acceptance 1-3 mechanical rather than prose.

**Generalizing for #1709.** The check table is `REQUIRED_OVERSEER_CHECKS = {"second-review": MEDIUM}`. Later slices add rows, such as the evaluator, without changing G1c.

**Not covered.** `overseer_merge.sh on-human-approval` (#2213) is not gated. A designated human's approval of the head is a human decision and outranks this check.

**Consequence.** An interactive overseer session cannot approve until a record exists. A human can create one by running `python3 -m scripts.automation.lib.overseer_second_review run --pr <N>` in their own terminal in the Overseer clone.

## AD-10: Head carried end to end, and every exit leaves an actor label

- **Head carry (item 5).** The findings file carries `reviewed_head`. `merge_authority_cli._cmd_route` pops that key before `canonicalize_findings_ex`, so the library schema is unchanged. It validates the value as 40-hex and compares it with the live `head_sha` (`:1207`). A mismatch raises `_Fail("head_moved", ..., "transient")` before any write. If any `sr-` entry is present, `reviewed_head` is required. This does not break Rule A (VF-11): the CLI still acts only on the head it fetched itself, and the field can only refuse, never redirect. The existing `_pin_head` (`:1384`) still closes the window between that check and the write.
- **Approval.** The approval head is G1c's `pre.head_sha`. The merge head is protected by `dismiss_stale_reviews`.
- **Actor labels (item 6).** For the hold paths, `hos-cron` applies `needs-human` mechanically (AD-3). For `route`, the existing step 4a text already requires `needs-ai` or `needs-human` on every `HOLD`, `ESCALATE`, `NOOP`, `LEGACY` and failure path. S1b's prose makes that text explicitly cover the `findings_file` route. `pending` is the one path that leaves no label, by design. It is transient, it is bounded by `pending-stuck` (AD-3), and G1c guarantees it can never become an approval.

## AD-11: Slicing

The repo limits a PR to 15 files and 10 commits. Each slice is independently mergeable and never weaker than today.

| Slice | Contents | Files | State after merge |
|---|---|---|---|
| **S1a**: runner, inert | `scripts/run_second_review.sh` (M, `--authority`); `scripts/automation/lib/overseer_second_review.py` (A); `scripts/automation/lib/merge_authority.py` (M, `keyed_flock` extraction); `tests/automation/test_overseer_second_review.py` (A); `SCRIPTS-INDEX.md` (M, regenerated); `docs/v0.7.0/ADR-2357-overseer-second-review.md` (this file); `docs/v0.7.0/TD-2357-S1a-overseer-second-review-runner.md` (A); `prompts/scripts/automation/lib/overseer_second_review.v2357.md` (A, prompt artifact) | 8 | Nothing calls the runner. The worker's `run_second_review.sh` path is unchanged. No behavior change. |
| **S1b**: wire and enforce | `bin/hos-cron` (M, phase, heartbeat, mechanical hold label, injection); `scripts/automation/pr_review_cli.py` (M, G1c, marker); `scripts/automation/merge_authority_cli.py` (M, `reviewed_head`, marker); `scripts/automation/lib/merge_authority.py` (M, `marker` argument on `record_pr_bounce`); `.claude/agents/overseer.md` (M, additive paragraph); `bootstrap/overseer-cron-prompt.md` (M, one sentence); `docs/LABELS.md` (M, `hos-cron` as a `needs-human` writer); `tests/automation/test_hos_cron.py` (M); `tests/automation/test_pr_review_resolution.py` (M); `tests/automation/test_pr_review_wrapper.py` (M); `tests/automation/test_merge_authority_cli.py` (M); `docs/v0.7.0/TECHNICAL-DESIGN-2357-S1b-*.md` (A) | 12 | The overseer's own run is authoritative, and approval is mechanically refused without it. Interim (a)/(b) are still active, which is stricter than today. |
| **S2**: retire the disclosure rules (item 10) | `.claude/agents/overseer.md` (M); `bootstrap/overseer-cron-prompt.md` (M); `tests/automation/test_route_pr.py` (M, anchors); `docs/v0.7.0/ADR-2357-overseer-second-review.md` (M, S2 landed note) | 4 | The second-review parts of (a)/(b) are removed. (c)/(d) stay. This unblocks #2358. |

- **S1b binding requirements from the S1a review.** The S1b TD must carry every one of these. Omitting one is an open correctness issue, not a deferral:
  1. Outer `timeout --kill-after=30 $_OSR_PER_PR_MAX` on every runner call, with 124 and 137 counted as `runner-failed` (AD-12, architect SF-1).
  2. The 3-strike limit covers `runner-failed`, `lock-busy` and `state-write-failed`. The `state-write-failed` counter lives outside `records/`, or the phase holds on the first occurrence (AD-12, architect SF-2 / reliability SF-3).
  3. G1c base pin: `record.base_sha == merge-base(pre.base.sha, pre.head_sha)` (AD-9, architect SF-3).
  4. A record integrity check before any record is consumed (AD-9, security SF-1).
  5. Posting hygiene (security / code-review NIT). Before anything is posted, vendor `detail` has `@mentions` neutralised (for example a zero-width joiner after `@`) and markdown links and images defanged. The OSR line regex accepts `-` for `tier` and `vendors` on a pending line written before the tier is known. The AD-4 marker never reads the tier's vendor requirement from a `pending-stuck` hold written before the tier was known. It writes `tier=-` and `vendors=-` for that hold.
- **`runs/` retention (TD-2357-S1a A3, decided).** This is a follow-up issue, filed with the S1a PR. It is not in S1a or S1b scope.
- **Ordering.** S1b depends on S1a. S2 depends on S1b plus one live cron cycle that writes records. The worker checks that in the Overseer clone's `.claudetmp/overseer-authority/second-review/records/` and in the markers on GitHub before it opens S2.
- **Contingency for S1b.** If S1b grows past 15 files, for example because another test file anchors approval behavior, split the route head-carry and bounce marker out into **S1c**, which covers `merge_authority_cli.py`, `merge_authority.py` and `test_merge_authority_cli.py`. S1c must land before S2. Until it lands, S1b's prose tells the model to run `review_worktree.sh --pr N --expect-sha <OSR head>` immediately before `route`, and to treat exit 4 as `pending`. G1c holds the approval side in either case.

## AD-12: Budget, lock and session cap

- **Per PR.** `_OSR_PER_PR_MAX = 3 x SECOND_REVIEW_VENDOR_TIMEOUT + 300` (3 x 900 + 300 = 3,000 s at the default). It is clamped to `_lock_ceiling - 300` and logged if clamped. The outer `timeout --kill-after=30` is a backstop only. The inner vendor timeouts end first. GNU `timeout` signals its process group, so the runner and `run_second_review.sh` die with it. A vendor process under its own inner `timeout` group can outlive the backstop by at most its own 900 s timeout (the same residual as #1146).
- **Per phase.** `_OSR_BUDGET` comes from `<project>_overseer_sr_budget` in `projects.conf`. It defaults to `HOS_CRON_MAX_SECONDS`, with 0 treated as 3,600, and is floored at `_OSR_PER_PR_MAX`.
- **Budget rule.** An uncached review starts only if `elapsed + _OSR_PER_PR_MAX <= _OSR_BUDGET` **or** no uncached review has run yet this cycle. Once the budget is spent, the remaining PRs run `--cache-only`, which costs no vendor call, so already-reviewed PRs stay approvable. Each cycle completes at least one new review, and records accumulate, so the queue always makes progress.
- **Session cap.** `HOS_CRON_MAX_SECONDS` keeps its meaning: the claude session's cap (VF-8). The phase does not count against it, so a slow review cannot eat the claude session's budget.
- **Lock heartbeat.** `touch "$_LOCK_DIR"` runs before each PR and once more just before claude starts. A contender measures age from the lock dir mtime (`:344-345`). So the pre-model phase never brings the lock near its ceiling, and claude starts with a full `2 x cap` window. Only the live holder runs the heartbeat. After the holder dies, staleness is still bounded by one ceiling from its last heartbeat, and the boot_id reclaim path (`:346-369`) is unchanged.
- **Outer bound is binding (S1a review, architect SF-1).** S1b wraps **every** runner call in the phase in `timeout --kill-after=30 $_OSR_PER_PR_MAX`, with no unwrapped call path. Exits 124 and 137 map to `pending reason=runner-failed` and count toward the A8 3-strike limit below. S1a also sets a finite inner `REVIEW_TIMEOUT = 3600` s (reliability SF-1), which supersedes TD-2357-S1a's `None`. The inner bound does not relax the outer one.
- **3-strike limit (TD-2357-S1a A8, extended by architect SF-2 / reliability SF-3).** The phase counts consecutive `runner-failed`, `lock-busy` and `state-write-failed` lines per `(pr, head)`, or per PR when no head is known. On the third, it applies `needs-human` and injects `verdict=hold` with that reason. `state-write-failed` can mean `records/` itself is unwritable, so the S1b TD must either keep that counter outside `records/` or hold on the first `state-write-failed`. It may not rely on a counter file in the directory that just failed.
- **Timeout breaker.** The breaker (`:2506-2567`) still counts claude timeouts only. Pre-model timeouts surface as `pending` or `hold` instead.
- **Worst-case cycle.** The longest a cycle can run is `_OSR_BUDGET + _OSR_PER_PR_MAX + HOS_CRON_MAX_SECONDS`. With this project's values that is 10,800 + 3,000 + 10,800, about 6.9 h, against a 21,600 s ceiling per heartbeat window. Cron fires during that time find the lock held and exit.

## Amendment traceability

| Item | Satisfied by |
|---|---|
| 1. The worker's ledger cannot clear the overseer's review; the state is the overseer's own | AD-8 (no ledger, `--record`/`--reset` refused), AD-2 (overseer-clone state, not `audit/log`, VF-10), test 7 |
| 2. Every tier vendor must succeed; no codex-for-agy | AD-8 availability preflight, AD-3 `vendor-missing`/`vendor-unavailable` holds, test 3 |
| 3. Trusted tools and config from main; explicit paths | AD-1 trusted-checkout precondition, AD-8 `--out-dir` and no cwd summary, VF-4, VF-9 |
| 4. Own cache, locking, atomic completion; failures retryable | AD-2, test 4 |
| 5. Expected head end to end | AD-1 `--expect-sha`, AD-10 `reviewed_head`, AD-9 G1c on `pre.head_sha`, `dismiss_stale_reviews` |
| 6. Every exit leaves an actor label | AD-3 mechanical hold label and `pending-stuck`, AD-10 |
| 7. No side effects in the runner | AD-8 (no `create_finding_issues`), test 8 |
| 8. No prior reports or dispositions in the prompt | AD-8 (digest omitted, no ledger), test 8 |
| 9. Oversized diffs never pass | AD-8 `diff-too-large` hold, whole diff with attributes neutralized; batching deferred to #1709 |
| 10. Remove (a)/(b) second-review parts in both files | AD-5 S2, AD-11 ordering |
| #2358. Countable from GitHub | AD-4 marker on verdicts and bounces, anti-forgery |

## Consequences and residual risks

- **Cost and duration.** There is one authoritative vendor run per head at MEDIUM and above, in addition to the worker's pre-check until #2358 decides whether the pre-check stays. Overseer cycles take longer by up to `_OSR_BUDGET`.
- **Raise loop delay.** A PR whose real tier exceeds both its floor and its declared tier waits one extra cycle. This is the AD-7 raise loop.
- **Trust assumption.** The worker can write neither the overseer clone's `.claudetmp/` nor its process environment. This is the sandbox boundary, and it is the same assumption the bounce lock and the overseer's local state already make.
- **Prompt consumption is not gated.** When agy reports no usage metadata, the shell writes a "Prompt consumption unverified" advisory section. That happens in 225 of 341 local agy reports. Truncation below the ceiling then cannot be ruled out, but the authority runner does not hold on it, because holding would hold most PRs. That would be a product change outside the 2026-11-15 ruling. Only a measured `prompt_not_consumed` holds. This residual belongs to #1718.
- **Out of scope.** The evaluator, security and reliability attestations (#1815, #2327, #1643); an independent composite tier (#1427); diff batching; the overseer running the deterministic checks itself (#1570).

## Startup-gap recovery

- **Should this have been settled earlier?** No. This is a reactive revision of an ADR that was never reviewed.
- **Affected sign-offs: none.** No design, code or sign-off was built against revision 1. The revision 1 commit `16f624a23` is superseded by this file. The stale local branch `worker-2357-overseer-own-second-review-261115203502-2982115` is a false started-branch signal.

## Open questions

None. Every decision above is technical and falls within the 2026-11-15 rulings.
