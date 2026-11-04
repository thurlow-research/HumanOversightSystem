# Prompt artifact — #2209 S1a (route/bounce core)

- **Issue:** #2209 (slice S1a)
- **Source files:** `scripts/automation/lib/merge_authority.py`, `scripts/automation/merge_authority_cli.py`, `bootstrap/merge_authority.sh`, `scripts/automation/lib/github.py`, `contract/OVERSIGHT-CONTRACT.md`, `SCRIPTS-INDEX.md`, tests under `tests/automation/`
- **Design:** `docs/v0.7.0/TECHNICAL-DESIGN-2209-s1-route-bounce.md` (architect APPROVED round 3 at `825ad19b8`), `docs/v0.7.0/ADR-2209-overseer-rejections-to-worker.md`, `docs/v0.7.0/REQUIREMENTS-2209-overseer-rejections-to-worker.md`
- **Model:** claude-opus-5-5[1m] (worker, autonomous cycle worker-hos-261031042001-2375947)
- **Date:** 2026-10-31
- **Risk tier:** HIGH (protected surface: `merge_authority.py`, `bootstrap/**`, `contract/**`)
- **Human review status:** the human ruled 1A 2A 3A 4C 5A on #2209 (ScottThurlow, 2026-10-31T18:02Z); 1A ruled all three Condition 10 matches false positives. CODEOWNER review still applies at merge.

## Prompt (as dispatched to `coder`)

Implement slice **S1a** of issue #2209 exactly as specified in `docs/v0.7.0/TECHNICAL-DESIGN-2209-s1-route-bounce.md` (architect-approved, round 3, commit `825ad19b8`). Read the whole TD first, then the ADR and REQUIREMENTS it cites. The TD is the contract: build what it specifies, no more. Do **not** implement any S1b item (§6: path holds, `/hos release-hold`, disputes, `dispute-ruling`, veto-window writes, `route-proceed`/`merge-guard`, `classify_merge_failure`, `record-escalation`). S1a's `route` never returns PROCEED (TD-D4).

Files (exactly the S1a list in TD §4; stop and ask if you need any other file):
1. `scripts/automation/lib/merge_authority.py`: additive. Existing public signatures keep working, and only the keyword-only defaults the TD names are added.
2. `scripts/automation/merge_authority_cli.py`: the `route` and `bounce` subcommands, overseer-only, with the exit codes and the `error_code`/`error_class` payloads of §3.16.
3. `bootstrap/merge_authority.sh`: header text, plus token minting for the new subcommands.
4. `scripts/automation/lib/github.py`: `list_issue_events`, `get_contents`, `list_check_suites_for_ref`. Follow the existing pagination, retry and no-truncation conventions in that file.
5. `contract/OVERSIGHT-CONTRACT.md`: the `pr-bounced` row and its JSON schema only (AR1-C4).
6. `tests/automation/test_bounce_gate.py`, including T-BG-10.
7. `tests/automation/test_route_pr.py` (new): the rule table, properties P1–P8, the reviewer-act, CODEOWNERS parity, cid, epoch and schema tests, T-GH-1, T-HT-1 (including the queued-run case), and the PR #2207 replay.
8. `tests/automation/fixtures/pr2207_0227Z.json` (new), as the TD describes it.
9. `tests/automation/test_merge_authority_cli.py`, including T-CLI-9.
10. `SCRIPTS-INDEX.md`: regenerate it with `bash scripts/framework/gen_scripts_index.sh`. Do not hand-edit it.

Rules:
- Keep the rulings the TD assumes behind the single constant or row it names: ESC-3 (A), ARCH-ESC-1 (A), and ESC-2 (C). That way a different human ruling is a one-line change.
- GitHub failures must fail closed exactly as §3.16 says. Never return a truncated list as complete.
- Tests must be hermetic: no network, and temp files only through pytest `tmp_path`. The suite enforces zero leaked temp entries.
- Self-flag per AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS). Do not edit `.claude/agents/**`.
- Run `scripts/oversight/.venv/bin/python -m pytest tests/automation -q` and make it pass. Then run `bash scripts/framework/run_tests_inner_loop.sh` and report the result.
- Commit when green: one commit, message `feat(#2209): S1a route/bounce core — issue-keyed bounce cid, epoch budget, same-head dedup, pure route_pr (S1a)`. End it with this single contiguous trailer block, with no blank line inside it:
  `Refs #2209`, then a blank line, then `Prompt-Artifact: prompts/scripts/automation/lib/merge_authority.v2209.md`, `AI-Model: claude-opus-5-5[1m]`, `AI-Risk: HIGH`, `Supervised-by: ScottThurlow` and `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  Never write a closing keyword (closes/fixes/resolves) in the message.
- Report: the files changed, the test results, the commit SHA, your self-flag, and any place you deviated from the TD, with the reason.

## Refinement iterations

The coder subagent ran on `claude-sonnet-5-5`; the worker session, which dispatched it, ran on `claude-opus-5-5[1m]`.

1. **Initial implementation** (`ed55d33dc`), following the prompt above.
2. **Gate fixes** (`2985e80e7`). `secret_scan` flagged the full 40-hex SHAs in the fixture, so they were replaced with synthetic low-entropy SHAs that keep the real 9-char prefixes (`_provenance` in the fixture). `type_check` errors were narrowed (mypy).
3. **Code-review round 1** (`1a647390f`). Fixed:
   - `base.sha` is validated before the CODEOWNERS read.
   - `list_issue_events` raises on a 404 or empty body.
   - `BounceAuditWriteError` gives an explicit post state.
   - `bounce` filters out already-bounced identities.
   - A closed sibling with no `closed` event exits 1.
   - `_COLLECTORS_COMPLETE_S1A` is a named constant.
4. **Code-review round 2** (`93900431b`). A closed or merged sibling with no actor login exits 1 (`epoch_sibling_missing`).
5. **Unit-test** (`b1236b04e`). Added 8 tests, including T-HT-1's queued-run case pinned with data.
6. **Security SF1/SF2 and ops advisory 1** (`e4dba2ee3`):
   - The bounce comment is capped at 60,000 characters.
   - `@` mentions and image/link markdown are neutralized.
   - `..` and `%2e` are rejected in URLs.
   - `comment_posted` is `null` when the post state is unknown.
7. **Security delta** (`de5ac6a21`). `<` is escaped, and `\` is rejected in URLs.

8. **Codex second review (CWE-703, medium) and architect rounds 4-5** (`be2f3c69f`):
   - The repair now handles five states (`repair_bounce_finalize`). It tells a deliberate ready-for-review apart from failed finalize writes using server-side issue events.
   - Rule 6c appends `repair-finalize`, and `actions` accumulate across rules.
   - Q5 was ruled option (1): rule 2's approved branch now returns RULING_REQUIRED (2k) and ESCALATE upheld-dispute (2l) before PROCEED.

9. **Codex final second review** (`d1eb8cf0e`):
   - **CWE-841 (fixed):** single-missing repairs are now suppressed by the matching deliberate event after T.
   - **CWE-362 (filed as #2227):** the bounce read-then-write is not serialized. #2227 must land before S2.

The reviewers' remaining items are S1b obligations in TD §6.3.

10. **Re-adoption and review hardening** (2026-11-04, `claude-sonnet-5-5` coder; worker session `claude-opus-5-5[1m]`):
    - **Re-adoption:** the work was re-adopted onto `worker-2209-s1a-route-bounce-261104055001-27768`.
    - **Merge with origin/main:** a union with #2213 (approval-merge, merge-provenance) and #2117/#1659 (revoke-only-minted).
    - **github.py:** the duplicate `list_issue_events` collapsed to the S1a version, replacing #2213's version and `_EVENTS_MAX_PAGES`. Behaviour is preserved for `approval_merge.py`.
    - **(a)** `allow_abbrev=False` on the top-level parser and every subparser in `merge_authority_cli.py`, so `--ap` is a usage error (exit 2) and agrees with the bash wrapper. Tests cover a read subcommand and `route`.
    - **(c)** `classify_github_error` classifies `ListTruncatedError` as deterministic (TD §3.16). The four CLI call-site special-cases stay as defence in depth. Unit test added.
    - **(d)** `bootstrap/merge_authority.sh` header: exit 3 reads `3 - route only: ruling-required (unreachable until S1b)` (TD §3.18).

11. **Second-review fixes** (2026-11-04, `claude-sonnet-5-5` coder):
    - **source_url link safety (agy medium, security L2, CWE-116):** `_same_repo_url` now rejects `( ) [ ] < > @ ! \`` so a URL cannot break out of the bounce comment's link. `_neutralize` escapes `&` first (security L1), so `&#64;name` cannot render as a mention. `#N` is not escaped.
    - **withdrawn by identity (agy medium, prompt-fidelity F8):** `route_pr` drops withdrawn rejections by `identity`, matching rule 6c. TD §3.8 names ids in `withdrawn_on_head` but not the bridge to a finding, so identity was chosen. Inert in S1a (`withdrawn_on_head` is stubbed).
    - **early findings-file parse (agy low):** `_route` parses the findings file before any GitHub call, so a malformed file gives `findings_file_invalid` on non-worker PRs too.
    - **gate fixes:** black formatting and a `set[str]` annotation in `test_merge_authority_wrapper.py`.
