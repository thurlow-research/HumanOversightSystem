# Prompt Artifact — merge_authority.sh

| Field | Value |
|---|---|
| **Generated file** | `bootstrap/merge_authority.sh` (also covers `bootstrap/pr_review.sh`, `tests/automation/test_pr_review_wrapper.py`, `tests/automation/test_merge_authority_wrapper.py`) |
| **Description** | #2117: wrappers revoke only a token they minted (pr_review.sh + merge_authority.sh + tests) |
| **Date** | 2026-10-20 |
| **Model** | claude-opus-5-5 (worker orchestrator); `coder` subagent authored the diff |
| **Risk level** | HIGH (validated by risk-assessor: diff_size floor + protected surface + token/identity handling) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Round 1 (worker → `coder`, verbatim apart from whitespace):

```
You are implementing a bug fix for issue #2117 in <repo-root> [absolute clone path redacted for portability_check], on the already-checked-out branch `worker-2117-inherited-token-revoke-261020092001-3976424`. Verify with `git branch --show-current` before you start and before you commit. Do NOT create or switch branches. Do NOT push, open PRs, comment on issues, or change labels.

## Bug
`bootstrap/pr_review.sh` and `bootstrap/merge_authority.sh` each register an EXIT trap that revokes whatever `GH_TOKEN` is in the environment, including a token **inherited from the caller** (e.g. the cron cycle's own installation token). That happens whenever the wrapper did not mint a token itself:
- `MINT_TOKEN=false`: an `--app` outside worker|overseer|human, or, for merge_authority.sh, the local-only subcommands `register` / `bounce-count`, which never mint. Under `bin/hos-cron` this revokes the cycle's token mid-cycle.
- the mint failed (the `else` branch that proceeds without a token).
Also, `merge_authority.sh`'s revoke_token inlines `curl -X DELETE -H "Authorization: token ${GH_TOKEN}"`. That is the pattern #1191 replaced with `bootstrap/revoke_app_token.sh`: it has no timeout and puts the token in curl argv.

## Required fix (both wrappers)
1. Inside the `if $MINT_TOKEN; then` branch, **before** calling get_app_token.sh, `unset GH_TOKEN GITHUB_TOKEN HOS_BOT_LOGIN HOS_EXPECTED_BOT_LOGIN`. A failed mint then never proceeds under an inherited identity. This matches the binding fix for the sibling wrapper in docs/v0.7.0/TECHNICAL-DESIGN-1520-S1-label-registry.md §7.1 step 3a; read that section for consistency. Non-minting invocations must leave the inherited environment untouched, so the CLI still sees it.
2. Track a flag (e.g. `_TOKEN_MINTED=0`, set to 1 only after a successful mint and source). revoke_token calls `bash "$SCRIPT_DIR/revoke_app_token.sh"` **only** when the flag is 1. TOKEN_FILE cleanup stays unconditional. Keep pr_review.sh's existing idempotency guard and INT/TERM signal handling intact.
3. merge_authority.sh: replace the inline curl with `bash "$SCRIPT_DIR/revoke_app_token.sh"`, gated by the same flag. Update its header "Requires:" line (it currently says curl is used for token revocation) and the comment block above revoke_token. Also fix pr_review.sh's comment that says "regardless of whether a token was ever actually minted (TOKEN_FILE / GH_TOKEN unset is a no-op below)", which is now wrong. Both wrappers' comments must explain *why*: an inherited token belongs to the caller, cite #2117. Match the existing comment density and style.
4. Do not change the stdout / exit-code pass-through contract (no JSON literals, no echo to stdout).

## Tests
- `tests/automation/test_pr_review_wrapper.py`: [read the Harness; add tests for (a) inherited GH_TOKEN + failed mint → no revoke curl call, inherited token not used; (b) inherited GH_TOKEN + non-minting --app → no revoke call; (c) successful mint → revoke exactly once with the minted token, never the inherited one. Update test_w16b, which forced HOS_BOT_LOGIN alongside a failed mint, to assert the new behaviour: inherited identity no longer leaks through a failed mint, exits 1 like W16a, no revoke call.]
- New `tests/automation/test_merge_authority_wrapper.py`, modelled on that harness: [real merge_authority.sh + revoke_app_token.sh in a tmp repo; stub get_app_token.sh, merge_authority_cli.py and curl. Cases: inherited GH_TOKEN with `register` → no revoke; `gate --app bogus` → no revoke; failed mint on `gate --app overseer` → no revoke and CLI sees no GH_TOKEN; successful mint → exactly one revoke of the minted token via revoke_app_token.sh; stdout/exit-code pass-through. pytest tmp_path only.]

## Verify / Commit
[run both wrapper test files + black --check; one commit with LOW trailers; stage only the 4 files; no closing keywords; report SHA and self-flag.]
```

## Constraints Specified

- Security: revoke only a token the wrapper minted; scrub inherited credentials before minting; never inline the DELETE curl (#1191).
- Contract: stdout is exactly one JSON object from the L2 CLI; exit code passes through unmodified; bash decides nothing (ARCH-3a).
- Must NOT: modify `revoke_app_token.sh`; touch non-minting invocations' environment; push/open PRs/edit issues.

## Refinement History

v1 (commit 0daedb506): scrub-before-mint + `_TOKEN_MINTED` gate + revoke via `revoke_app_token.sh`; tests for both wrappers. code-reviewer APPROVED.

v2 (commit 127e64891), from security-reviewer SHOULD_FIX ×2 + NITs, prompt (summarised): after a failed mint, `merge_authority_cli.py` has no `HOS_BOT_LOGIN` guard, so `gh` falls back to the host's stored login — export an empty `mktemp -d` `GH_CONFIG_DIR` on the failed-mint branch only (both wrappers, removed in revoke_token), with tests; add INT/TERM `_on_signal` + idempotency guard to merge_authority.sh with a SIGTERM test; correct comments that claimed `revoke_app_token.sh` keeps the token out of argv (it does not — pre-existing, out of scope); add `HOS_PR_REVIEW_TOKEN_MINT_FAILED` to the pre-mint unset; test NITs. security-reviewer re-verified: APPROVED.

v3 (commit 14528a647), from risk-assessor brief item 1, prompt (summarised): a signal between `source "$TOKEN_FILE"` and `_TOKEN_MINTED=1` (or a partial `source` failure) skips revoking a live minted token — set the flag (renamed `_MINT_ATTEMPTED`) immediately after the scrub, since any `GH_TOKEN` present after it can only be the wrapper's own, and on a failed mint `revoke_app_token.sh` is a documented no-op.

v4 (commit 869c6368a), from ops-reviewer SHOULD_FIX + NIT, prompt (summarised): print the failed-mint warning before `mktemp -d` so a tmpfs-full abort under `set -e` still tells the operator a mint failed; reword it to "proceeding without credentials (inherited identity scrubbed)".

All four rounds were squashed into a single commit on the branch.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `bootstrap/merge_authority.sh` and `bootstrap/pr_review.sh`
4. Note any drift in a new version artifact (`merge_authority.v1.md`)
