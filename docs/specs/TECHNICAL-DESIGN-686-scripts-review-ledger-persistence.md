# Technical Design — #686: Persist the scripts-review dedup ledger in-repo

**Document type:** Technical design
**Status:** Implemented (bounded slice — improvement #5 of 6)
**Issue:** #686
**Related:** SPEC-334 (validation_logic.py), DECISIONS.md (2026-06-27)
**Author:** worker (autonomous), reviewed against an independent architectural pass
**Date:** 2026-06-27

---

## 1. Scope and intent

Issue #686 ("scripts-review gate non-determinism") proposes six improvements to
make the Phase 1.6 scripts-review release gate converge. This change implements
**only improvement #5** — persist the dedup ledger in-repo — and structurally
enables #6 (release-time pre-seed). The other four improvements (semantic dedup,
product-scope exclusion, convergence criterion, 2-of-3 reviewer agreement) are
deferred as separate, higher-fail-open-risk designs (see §5).

The gate (`scripts/framework/validate_scripts.sh`) converges when a pass produces
zero NEW (un-ledgered) blocking findings. Its ledger lived in gitignored
`.claudetmp/framework/scripts-review-ledger.jsonl`, so every machine and every
fresh clone started with an empty seen-set and re-litigated already-triaged
findings — a primary driver of the v0.4.0 non-convergence incident.

## 2. Change set

Exactly these artifacts change:

1. `scripts/framework/validate_scripts.sh`
   - `LEDGER` now resolves to the committed path
     `"$ROOT/scripts/framework/scripts-review-ledger.jsonl"`, overridable via
     `HOS_SCRIPTS_REVIEW_LEDGER` (tests). `PASS_COUNT_FILE` and the timestamped
     output files stay ephemeral under `.claudetmp/framework/`.
   - `--record` ensures the ledger's parent dir exists before delegating to
     `validation_logic.py record` (append).
   - `--reset` **truncates** the (now-tracked) ledger and removes the pass
     counter, instead of `rm`-ing the ledger file.
2. `scripts/framework/scripts-review-ledger.jsonl` — new, committed, empty.
3. `docs/specs/SPEC-334-*.md` — note the persistent ledger + truncate-on-reset.
4. `DECISIONS.md` — dated decision entry.
5. `tests/framework/test_scripts_review_ledger.py` — new contract tests.

`validation_logic.py` is **not** modified: `load_ledger` already tolerates a
missing/empty file and the fingerprint/verdict logic is unchanged.

## 3. Fail-closed invariant (the load-bearing property)

The scripts-review gate is fail-CLOSED by design (#669/#670): a hung, empty, or
erroring reviewer must never converge to PASS. This change preserves that:

- `load_ledger` only ever **adds** fingerprints to the `seen` set. A larger
  `seen` set can convert un-ledgered blocking findings into known ones — never
  the reverse. It cannot manufacture an `approve`.
- An empty committed ledger ≡ the old missing-ledger state (empty seen-set), so a
  clean checkout is behaviorally identical to before.
- The `verdict="error"` paths — required-Opus hang guard (synthesized blocking
  finding) and the `--strict-empty` empty-parse case — are computed independently
  of ledger contents and always count as NEW blocking. Ledger contents cannot
  suppress them.

## 4. `--reset` lifecycle and the asymmetry

Because the ledger is tracked, `--reset` truncates rather than deletes so the
tracked file stays in place. `--reset` remains the "start a clean review of a new
change set" affordance. To clear the shared baseline for everyone, commit the
emptied file; otherwise `git restore` it after a local run.

Only the scripts-review ledger is persisted. `validate_agents.sh` /
`validate_self.sh` keep their ephemeral `.claudetmp/` ledgers and delete-on-reset
behavior — they review the smaller, more stable agent/contract surface and have
not shown the cross-machine convergence failure. The asymmetry is intentional;
unifying it is out of scope.

## 5. Deferred improvements (file as follow-ups)

| # | Improvement | Why deferred |
|---|---|---|
| 1 | Semantic/embedding dedup | New infra + model dependency; large surface |
| 2 | Scope gate to product scripts (infra-exclusion list) | Judgment-heavy; excluding a script that should gate is a fail-open risk |
| 3 | Convergence criterion vs. fixed 3-pass cap | Changes pass-cap control flow; own fail-open surface |
| 4 | 2-of-3 reviewer agreement before "new" | Downgrades single-reviewer real bugs to non-blocking — fail-open risk |
| 6 | Automated release-time pre-seed | Enabled structurally by #5; automation is a separate change |
