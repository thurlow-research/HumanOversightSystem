# Technical Design — Issue #360: run_review_chain.sh Auto-Detect Changed Files

**Status:** For implementation — architect GO
**Step:** v0.4.0
**Author:** technical-design agent
**Spec:** `docs/specs/SPEC-360-review-chain-autodetect.md`
**Date:** 2026-06-16

RISK: LOW | CONFIDENCE: HIGH | Change class: additive

---

## Architect bindings (binding)

| # | Binding |
|---|---|
| B1 | Auto-detect runs BEFORE tier resolution — the file list feeds validators → `summary.json` → tier. The detected list must be present in `EXTRA_VALIDATOR_ARGS` before `resolve_tier()` runs (which is already after parsing; binding is satisfied as long as detection happens during/just after arg-parse and before Step 1). |
| B2 | Pass ALL changed files unfiltered. Validators do their own type filtering. No `.py/.sh/.js` allow-list (resolves OQ-2). |
| B3 | Detached HEAD: resolve `origin/main` to a concrete SHA first. If `git describe` fails, fall back to `HEAD~1..HEAD` with a warning. If `HEAD~1` also fails (shallow clone / single commit), exit non-zero directing the operator to use explicit paths. |
| B4 | Never diff against a bare symbolic `HEAD` ref — always resolve to concrete SHAs before diffing. |

---

## Component map

| # | Artifact | Type |
|---|---|---|
| A | `scripts/run_review_chain.sh` — arg parser: add `--since-tag` / `--since-main` flags + mutual-exclusion check | edit |
| B | `scripts/run_review_chain.sh` — new `autodetect_files()` function (resolves SHAs, runs the diff, logs mode + count) | edit |
| C | `scripts/run_review_chain.sh` — call site after parse, before tier resolution; populate `EXTRA_VALIDATOR_ARGS` only when empty | edit |
| D | `scripts/run_review_chain.sh` — header comment block (used by `--help`) updated to document the three modes | edit |

No new files. No new tests (`bash -n` is the gate per task).

---

## Contract

### Arg-parse surface (A)

Two new boolean flags added to the `while` loop:

- `--since-tag` → sets `SINCE_MODE=tag`
- `--since-main` → sets `SINCE_MODE=main`

New state variable initialized before the loop: `SINCE_MODE=""`.

Mutual-exclusion (R6 / AC-7): when a `--since-*` flag is parsed and `SINCE_MODE` is already non-empty with a *different* value, `die` with a clear message. Implemented by checking `[[ -n "$SINCE_MODE" ]]` before assigning, since only the two flags write it.

The existing positional-arg and `--` handling are unchanged (R5 / AC-8): bare paths and `-- <paths>` still append to `EXTRA_VALIDATOR_ARGS`.

### Auto-detect resolution (B, C)

After the parse loop completes and before `resolve_tier()`:

```
if EXTRA_VALIDATOR_ARGS is empty:
    mode = SINCE_MODE or "tag"        # default tag (R1, spec §3 priority 3)
    autodetect_files mode             # appends detected paths to EXTRA_VALIDATOR_ARGS
elif SINCE_MODE is non-empty:
    warn "--since-<mode> ignored: explicit paths provided"   # explicit wins (spec §3 priority 1)
```

The "explicit paths still work" requirement (R5) is enforced by gating the entire
autodetect block on `EXTRA_VALIDATOR_ARGS` being empty at parse-time.

### `autodetect_files(mode)` algorithm (B)

Resolves a concrete diff range, never diffing a bare symbolic ref (B4).

**mode = main** (`--since-main`, R3 / AC-5, AC-6):
1. `base=$(git rev-parse --verify --quiet origin/main)` — resolve to SHA (B3, B4).
2. If empty → `die` with message: cannot resolve `origin/main`; use explicit paths or `--since-tag`.
3. `head=$(git rev-parse --verify --quiet HEAD)`; if empty → `die`.
4. `files=$(git diff --name-only "$base" "$head")`.
5. Log: `info "auto-detect mode: since-main (git diff <base-sha>..<head-sha>)"`.

**mode = tag** (`--since-tag` / default, R2 / AC-3, AC-4):
1. `tag=$(git describe --tags --abbrev=0 2>/dev/null || true)`.
2. If `tag` non-empty:
   - `base=$(git rev-parse --verify --quiet "${tag}^{commit}")` — resolve tag to commit SHA (B4).
   - Log: `info "auto-detect mode: since-tag (tag=$tag → <base-sha>..HEAD)"`.
3. If `tag` empty (no tags) → fallback (B3):
   - `warn "no git tag reachable from HEAD — falling back to HEAD~1..HEAD"`.
   - `base=$(git rev-parse --verify --quiet HEAD~1)`.
   - If empty (shallow clone / root commit, B3) → `die`: cannot resolve `HEAD~1` (shallow clone or single commit); re-run with explicit file paths.
   - Log: `info "auto-detect mode: since-tag (fallback HEAD~1..HEAD)"`.
4. `head=$(git rev-parse --verify --quiet HEAD)`; if empty → `die`.
5. `files=$(git diff --name-only "$base" "$head")`.

**Common tail (both modes):**
- Count: `n=$(printf '%s\n' "$files" | grep -c . )` (0 when empty).
- If `n == 0` (R4 / AC-9): `warn "auto-detect: diff range was empty (0 changed files) — validators will run with no file arguments"`. Do **not** append anything; do not exit. `EXTRA_VALIDATOR_ARGS` stays empty and validators receive no files (preserves the pre-existing no-file path; this is the documented R4 behavior, not a silent success because the warning is emitted).
- If `n > 0`: append each non-empty line to `EXTRA_VALIDATOR_ARGS`; log `info "auto-detect: $n changed file(s) detected"` (R7 / AC-2 — these feed validators → summary.json → real tier, not CRITICAL fallback).

All `git diff` invocations use two concrete SHA args (`git diff "$base" "$head"`), never `base..HEAD` with a symbolic HEAD (B4). `--name-only` is preserved per spec §3.

### Help text (D)

The header comment block (lines 9–11, the Usage section read by `--help` via `sed -n '2,28p'`) gains:
- The three input modes (explicit / `--since-main` / `--since-tag`).
- Default = `--since-tag` when no file args and no `--since-main`.
- `--since-tag` fallback to `HEAD~1..HEAD` when no tag exists.
- Mutual exclusion of `--since-tag` and `--since-main`.

Because `--help` echoes the header via `sed`, the new flag docs must live inside lines 2–28. The Usage and "Tier resolution order" comment block is extended accordingly (R8 / AC-10).

---

## Boundaries

- **Must not** filter the file list by extension (B2). Validators own filtering.
- **Must not** alter `run_validators.sh`, `run_second_review.sh`, or `run_panel.sh` (spec §2).
- **Must not** engage autodetect when any explicit path is present (R5).
- **Must not** diff a bare symbolic `HEAD` (B4) — every diff uses resolved SHAs.
- **Must not** change idempotency-sentinel behavior (spec §5).
- Autodetect runs once, after parse, before `resolve_tier()` / Step 1 (B1).

---

## Acceptance trace

| AC | Satisfied by |
|---|---|
| AC-1, AC-2 | autodetect populates files → validators produce real summary.json → real tier |
| AC-3 | `autodetect_files tag` with a tag present |
| AC-4 | tag-empty fallback path + warn |
| AC-5 | `autodetect_files main` |
| AC-6 | `origin/main` unresolved → die |
| AC-7 | mutual-exclusion check in parser |
| AC-8 | autodetect block gated on empty `EXTRA_VALIDATOR_ARGS` |
| AC-9 | empty-diff warn, no silent success |
| AC-10 | header/help text update |
| AC-11 | `bash -n` |
