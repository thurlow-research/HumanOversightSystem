# Prompt Artifact — ensure_venv.sh

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/ensure_venv.sh` (+ `bin/hos-cron`, `tests/automation/test_ensure_venv.py`, `tests/automation/test_hos_cron.py`, TD-2204 follow-up note, `scripts/automation/lib/cycle_log.py` docstring) |
| **Description** | MCP pre-install refusal diagnosability: reason line, cron log tail + audit detail, violation-only negative cache (#2220) |
| **Date** | 2026-11-06 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Issued by the autonomous worker to the `coder` subagent (v1, verbatim except
the git-hygiene preamble and commit-trailer block, which are boilerplate):

```
You are implementing GitHub issue #2220 in the HOS repo, on the already-checked-out
branch. Commit your work on this branch when done (one commit). Subject line:
`fix(ensure-venv): surface MCP pre-install refusal reason in cron log + audit; cache
deterministic refusals (#2220)`.

## Background
`scripts/oversight/ensure_venv.sh` `_create_venv` runs the MCP approved-list check
(`scripts/oversight/mcp_policy_logic.py`, exit 1 = violation, any other non-zero =
cannot check) inside a fresh venv before any pip install, and on refusal removes the
venv and returns 1. Design context: `docs/v0.7.0/TECHNICAL-DESIGN-2204-mcp-preinstall-check.md`.
`ensure_venv.sh` is both SOURCED by many scripts (gates, validators) and RUN as a
subprocess by `bin/hos-cron`. Read both files fully before editing.

## Required changes (design decisions already made — implement exactly)

1. Machine-readable reason line (ensure_venv.sh). Do NOT change exit codes (sourcers
   depend on exit 1). Instead, on each policy refusal path in `_create_venv`, emit to
   stderr one stable line `HOS_VENV_FAILURE_REASON=<reason>` where reason is:
   - `mcp_policy_preinstall_refused` — policy checker exit 1 (violation)
   - `mcp_policy_preinstall_cannot_check` — checker exit not 0/1, OR the guard files
     (mcp_policy_logic.py / mcp_approved_list.json) are missing.
   Keep the existing human-readable `_evenv_err` messages.

2. hos-cron shows the reason (bin/hos-cron). In `_validate_env`, stop discarding stderr
   (`2>/dev/null`). Capture ensure_venv.sh stderr to a temp file made with `mktemp`
   (respecting `$TMPDIR`; clean it up), and on failure print the last ~10 lines into the
   cron log (stdout, prefixed with `$LOG_PREFIX`), keep the existing "oversight-venv
   broken or missing — validators will not run" line, and keep `_validate_env`
   fail-open (return 0). In both `_validate_env` and `_pre_jitter_deps_check`, parse the
   `HOS_VENV_FAILURE_REASON=` line (last one wins; whitelist the value to `[a-z_]+`) and
   include it in the audit: `_pre_jitter_deps_check` currently emits
   `_audit cycle-preflight-fail reason=oversight_venv_build_failed` — keep that reason
   value and add `detail=<parsed reason>` when one is present. `_validate_env` currently
   emits no audit; when a parsed reason is present, emit
   `_audit cycle-env-warn reason=oversight_venv_unavailable detail=<parsed reason>`
   (register the event if an allowlist/schema exists). `_pre_jitter_deps_check` already
   shows stderr — keep that while also parsing it.

3. Negative cache for deterministic refusals (ensure_venv.sh). Only the violation case
   (checker exit 1) is deterministic; cannot-check may be transient and must NOT be
   cached. Key = sha256 of the contents of `requirements.txt`, `mcp_approved_list.json`,
   and `mcp_policy_logic.py`. Cache file:
   `~/.hos/setup-validation/mcp-policy-refused-${REPO_HASH}` containing the key. In
   `_create_venv`, after the guard-file check and BEFORE `rm -rf "$VENV"` /
   `python3 -m venv`, if the cache file exists and equals the current key, skip venv
   creation, print an `_evenv_err` explaining the cached refusal and how to clear it,
   emit `HOS_VENV_FAILURE_REASON=mcp_policy_preinstall_refused`, return 1. On a fresh
   violation write the key (best-effort). On a successful policy check, delete the cache
   file. sha256sum, else `shasum -a 256`, else skip caching (never fail). The cache can
   only cause a refusal, never an approval. Tests must point HOME at a tmp dir.

4. Document the smoke-fail rebuild trade (item 4) in the ensure_venv.sh header, and
   append a "Follow-up (#2220)" note to TD-2204 recording the four decisions.

## Tests (required)
- test_ensure_venv.py: reason line for violation, cannot-check (each non-1 code) and
  missing guard file; violation writes cache; cache hit does NOT call the checker or
  `python3 -m venv` and still exits 1 with the reason line; changing an input
  invalidates the cache; cannot-check does not write cache; successful check removes a
  stale cache file.
- test_hos_cron.py: stub writing VIOLATION + reason to stderr and exiting 1 → VIOLATION
  text in the cron log, audit record carries the detail; a reason with non-[a-z_]
  chars is not propagated.

Verify with the targeted pytest files and `bash -n`; keep the diff tight.
```

## Constraints Specified

- Exit codes of `ensure_venv.sh` unchanged (it is sourced; sourcers rely on exit 1).
- `_validate_env` stays fail-open; `_pre_jitter_deps_check` still exits 78 and still
  shows stderr; existing `reason=` audit values preserved.
- Reason values whitelisted to `[a-z_]+` before reaching audit records.
- Negative cache may only ever cause a refusal; "cannot check" never cached; cache I/O
  best-effort; tests isolate `HOME`.
- Temp files via `mktemp` under `$TMPDIR`, cleaned on every path.
- Must NOT: change branches, push, file issues/labels, use git stash/checkout.

## Refinement History

- **v1** (079eff4f7): the brief above.
- **v2** (fbcb2f416), from the inner-loop review findings:
  - `$HOME` read lazily inside `_create_venv` as `${HOME:-}`, with no caching when it is
    empty (code-review SHOULD_FIX).
  - Cache only on rc 1 **with** a `VIOLATION:` line. The checker output is captured via
    mktemp and re-emitted. rc 1 without that line counts as cannot-check and is not
    cached (reliability SHOULD_FIX-1).
  - Delimiter-safe per-file key (security NIT).
  - `_evenv_policy_key` never fails under `set -e` (reliability NIT-1).
  - CR and control characters stripped from the logged tail (security SHOULD_FIX).
  - `cycle-env-warn` emitted on every failure, with `detail=unknown` as the fallback
    (ops SHOULD_FIX).
  - The unit-test MUST_FIX/SHOULD_FIX gaps were added.
- **v3** (cd81063c7), from the round-2 reviews:
  - The mktemp-failure fallback uses `>&2` instead of `>/dev/stderr`, which truncated a
    file-backed stderr (reliability NIT-4).
  - The preflight audit always carries `detail=${reason:-unknown}`.
  - Tests added for the fallback and for temp-file cleanup.
- **v4** (6bc28e4f8): gate-only fixes.
  - black formatting and E501 wraps.
  - An `_evenv_reason` helper and test constants clear detect-secrets false positives on
    the `HOS_VENV_FAILURE_REASON=<token>` literals.

Full per-round findings: `.claudetmp/signoffs/step2220-register.md` (uncommitted
working state).

## Human Review Notes

<!-- After human review, record findings here. -->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `scripts/oversight/ensure_venv.sh` and `bin/hos-cron`
4. Note any drift in a new version artifact (`ensure_venv.v2.md`)
