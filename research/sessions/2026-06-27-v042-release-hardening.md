# Session: v0.4.2 release hardening + autonomous-loop branch hygiene (2026-06-23 → 06-27)

**Dates:** 2026-06-23 through 2026-06-27
**Branches:** numerous bot branches; synthesis written on `feat/686-scripts-review-ledger-persistence`

This is a *run-period* session log, not a single working session: it captures the research-relevant output of the standing autonomous worker/overseer loop and the human-supervised fixes between the last research update (2026-06-22) and 2026-06-27.

---

## What happened

The v0.4.2 release was hardened, the last-line gate was institutionalized into the overseer, and several failure modes specific to the *standing autonomous loop* surfaced and were closed. The period is dominated by oversight-machinery bugs (fail-opens, staleness/freshness, convergence) rather than application features — the system tightening its own controls.

### Fail-opens caught at the release boundary (O4, O8)
- **#814 — three fail-opens, all caught by the v0.4.2 pre-release validation pass** (`run_framework_validation.sh`, run by Opus), none by the inner-loop reviewers that had approved the code:
  1. `validate_docs.sh` / `validate_spec_compliance.sh` gated on the reviewer's self-reported `verdict` field instead of the computed `blocking_count` — a JSON listing blocking findings but tagged "approve" exited 0. → new finding `gate-on-computed-signal-not-self-reported-verdict.md`.
  2. `bash_check.sh` quote-context tracker counted quotes inside comments, so a comment with an odd quote (`# 5" pipe`) toggled `in_dquote` and silently skipped the next real code line — portability gate fail-open.
  3. `migration_scorer.py` passed hardcoded line 0 to the AddField null-check, so the context window always scanned the file header — every AddField scored HIGH (over-flagging false positive, the opposite-direction failure).
- **#806/#807** — `ensure_venv.sh` now smoke-tests the oversight venv on every invocation and auto-repairs, instead of trusting a stale cached success marker.
- **#774** — `hos-cron` fails *closed* (exit 78, actionable) when venv/pytest is missing *before* the jitter sleep, rather than burning 30–60s and failing opaquely later.

### Last-line gate institutionalized (O8)
- **#695 / #815** — overseer release-gate deep validation: on detecting an open release-request issue, the overseer re-reads every per-step `summary.json` from `main`, re-checks tier/severity and sign-off-register completeness for required roles, and posts CLEARANCE or ESCALATE before any release authorization. The O8 "manual last-line pass" became standing mechanism.

### Autonomous-loop branch hygiene (O9, recorder-in-recorded-set)
- **#850** — pre-PR stale-commit guard (`stale_commit_detector.py`, 33 tests): git-cherry patch-id matching detects commits already in `main`; SHA-overlap against open PRs handles the in-flight sibling case; redundant commits stripped by rebase. The worker had been re-proposing already-merged work. → new finding `autonomous-worker-restacks-redundant-work.md`.
- **#880** — guard against committing the append-only audit log onto feature branches (which shifted PR HEAD past the validator artifact and tripped the overseer's §3b freshness gate); §3b moved from exact `head_sha` equality to an ancestry-based check immune to non-code tail commits.
- **#861** — audit logs now sync to a dedicated `audit-log` branch via Actions, keeping the recorder out of feature diffs entirely.

### Convergence (O3, O8)
- **#686** — moved the scripts-review dedup ledger from gitignored `.claudetmp/` to the committed `scripts/framework/scripts-review-ledger.jsonl`. The ephemeral location was the root cause of the v0.4.0 scripts-review non-convergence (10+ attempts, `--skip-validation` required): the ledger reset on every clone, so "zero-NEW" collapsed to the unreachable "zero". → new finding `convergence-ledger-must-persist.md`.

### Autonomous-loop ergonomics (O9, O10)
- **#867** — worker PR routing checks **mergeable** before review state; a CONFLICTING PR carrying a prior APPROVED review had been skipped as "awaiting-merge" (O10 enumeration gap, the inverse of #411/#414).
- **#901** — priority-based work selection (`priority:*` ladder, FIFO within a band, one shared `next_candidates.jq`); the worker had selected purely by lowest issue number (O9 "take the next ticket" bias).
- **#778** — `hos-suspend` CLI: pause a project's cron cycle via an auditable JSON marker (fail-closed) instead of editing crontab — a graceful safety valve (O7 / brownfield).
- **#792** — pre-compute cycle context and inject it into the Claude prompt (perf; removes ~6–8 discovery API calls/cycle).
- **#817 / #780** — de-hardcode the target milestone in the worker cron prompt (config-driven sentinels).

---

## Research findings filed

- `convergence-ledger-must-persist.md` (#686) — the dedup ledger that defines a forced/last-line gate's reachable "pass" must persist in-repo, or the gate never converges. Extends `operationalizing-a-nondeterministic-reviewer-as-a-gate.md`.
- `gate-on-computed-signal-not-self-reported-verdict.md` (#814) — a gate must recompute its verdict from the findings, never trust the reviewer's self-reported `verdict`. Generalizes `self-classification-cannot-gate-the-human-boundary.md` to the reviewer layer.
- `autonomous-worker-restacks-redundant-work.md` (#850, #880) — a standing autonomous worker re-proposes already-merged work unless a fail-closed pre-PR check re-derives "is this already done?" from durable history.

OBSERVATIONS.md updated with new evidence under O3, O4, O8, O9, O10. Future-finding candidates added to `findings/README.md` gaps list: institutionalizing the last-line gate (#695/#815) and the graceful safety valve (#778).

---

## The throughline

Almost every incident this period is the *oversight machinery* failing, not the application — and the characteristic catch was the **last-line / pre-release pass finding fail-opens the inner-loop reviewers had approved past** (#814, three at once). The period also surfaced a distinct hazard class: the standing autonomous loop accumulates state *between* cycles (stacked branches, committed audit logs, a reset ledger) that a human-in-the-loop process never does, and several fixes are the same shape — *re-derive against durable shared state, never trust the loop's local/ephemeral view* (the git analogue of O1's "agents can't self-certify").
