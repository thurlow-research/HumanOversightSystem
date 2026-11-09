# TECHNICAL-DESIGN-2288-S1: remote janitor — `reap-orphans --remote-scope all` (#2288 slice 1, child of #2285)

**Status:** APPROVED (architect, 2026-11-09). Architect note: consistent with TD-2286 and `readopt.py` as built; listing claim re-verified; approved with the architect edits marked *[architect]* in §6 (S13, S14) and §8 (long-lived integration branches, binding on the cron-wiring slice).
**Binding input:** the #2288 issue body (item 1), which is the requirements spec. It extends the approved TD-2286 (`docs/v0.7.0/TECHNICAL-DESIGN-2286-reap-orphans.md`), whose slice table hands non-worker remote heads to #2288. Everything TD-2286 specifies stays in force unless this addendum says otherwise.
**Change class:** additive. This adds a new opt-in flag. The default keeps today's behaviour, so no existing caller or sign-off is affected, and there is no startup gap.
**Contract only.** This document contains no implementation.

## 0. Scope

| In (this slice) | Out (later #2288 slices) |
|---|---|
| `reap-orphans --remote-scope {worker,all}`, tests, docstring and usage text | Item 2: delete-on-close in PR-closing paths. Item 3: `hos_repo_sync` prune. Item 4: metrics. Cron wiring. |

#2288 item 1 asks for the same decision table that TD-2286 §2 already applies. The only missing piece is the remote listing, which is limited to `worker-*` today. This slice widens that listing and leaves the decision table alone.

## 1. Flag

- **CLI:** `reap-orphans … [--remote-scope {worker,all}]`, using argparse `choices`.
- **Default:** `worker`, which is exactly the current behaviour.
- **Function:** `reap_orphans(..., remote_scope: str = "worker")`. Any other value raises `ValueError` before the run reads or deletes anything. Only programmatic callers can hit this; the CLI already restricts the choices.

## 2. Listing mechanics

**Verified** against git 2.x on a local bare repo with heads `main`, `fix/foo`, `release/0.5.x`, `a/b/c` and `worker-1-a`:
- `git ls-remote --refs <url> 'refs/heads/*'` returns **all five**. The `*` in an ls-remote pattern crosses `/`, because the pattern is not matched path-wise.
- `--heads` with no pattern returns the same set.
- `'refs/heads/worker-*'` returns only `worker-1-a`.

**Contract:**
- With `all`, `reap_orphans` calls `remote_heads("refs/heads/*")`. With `worker`, it calls `remote_heads("refs/heads/worker-*")`, unchanged.
- Use the pattern form, not `--heads`. That keeps the existing `RemoteHeads = Callable[[str], list[tuple[str, str]]]` seam and `_ls_remote(run, url, pattern)` unchanged. Tests inject a fake `remote_heads` or use the bare-repo origin, and can assert which pattern they received.
- ls-remote patterns are tail-matched. `_ls_remote` already keeps only refs that start with `refs/heads/` and strips that prefix, so a non-branch ref whose tail matches never becomes a candidate. That filter must stay.
- **Name filter:** the `name.startswith("worker-")` filter is applied **only** when the scope is `worker`. With `all`, every listed name becomes a remote `_Ref`.
- Every name still goes through N1 (`unsafe-name`) first. A name that fails N1 can never reach a git argument or an output line.

## 3. Decision table: unchanged

Each remote head goes through TD-2286 §2 and §3 exactly as it does today. Under `all` this means the following for non-worker names:

| Rule | Effect on a non-worker remote head |
|---|---|
| N2 | `main`, `audit-log`, `release/*` and `audit/*` are KEEP `protected-name`. This rule comes before every D-rule, so a landed head with one of these names is still kept. |
| N3/N4 | Not applied to remote refs (as today). |
| `remote-tip-not-local`, G1 | As today. Age is the remote tip's committer date (TD-2286 §10 post-review note). |
| N5 | Any open same-repo PR with `head.ref == name` gives KEEP `open-pr`. The pre-delete open-PR re-check also applies. |
| D1 | A covering merged PR into `main` gives REAP `pr-merged`. |
| D1' | A covering closed, unmerged PR gives REAP `pr-closed`. The A1 open-issue block is local-only (`ref.where == "local"` in `_decide_rest`), so remote heads never had it. |
| D2 | **Never applies.** `_WORKER_RE` is anchored with `.match(r"worker-(\d+)-")`, so a non-worker name gets `plan["issue"] = None`. `_decide_rest` then skips D2, `_commit_issue_refs` is not called, and the name adds nothing to `needed`. That means no issue-state reads for these names. A name like `fix/worker-12-x` does not match either. |
| D3a/D3b | REAP `landed-ancestor` or `landed-content`. |
| Otherwise | KEEP `unlanded-pr-sha-mismatch` or `unlanded-no-pr`. The head is reported, not deleted, which is #2288's rule that a branch with no PR is reported unless its content is fully on main. |

Deletion uses the existing batched compare-and-swap push (TD-2286 §3.2), the auth env and redaction (§3.3), the allowed-URL rule (A7) and `--max-deletions`, all without change.

## 4. Interaction with `--local-only`

**Decision: it is a usage error.** Passing `--remote-scope` explicitly together with `--local-only` exits 2, and nothing is read or deleted.
- **Mechanism:** the argparse default is `None`, which resolves to `worker` after the conflict check. That way, only an explicit flag counts as a conflict.
- **Why not a silent no-op:** the flag widens what gets deleted. An operator who combines it with `--local-only` has written a self-contradictory command, and refusing it costs nothing. `--remote-only` combined with either scope is valid.

## 5. Output, SUMMARY and docs

- Line formats, field order (A8), reason tokens and the `SUMMARY` fields are **unchanged**. Under `all`, `main` and `audit-log` now show up as `KEEP … reason=protected-name where=remote` lines in dry-run output and are counted in `kept=`. Nothing else changes.
- **Module docstring:** the Usage line gains `[--remote-scope worker|all]`. The `reap-orphans` subcommand blurb becomes "remote ``worker-*`` heads (``--remote-scope all``: every remote head, #2288)".
- **Function docstring:** the `reap_orphans` docstring gets the same change.

## 6. Tests (`tests/automation/test_readopt.py`)

These use the existing `repo` fixture (bare-repo origin), fake `pulls` and `issue_states`, and an injected `now` outside the grace window unless a row says otherwise.

| # | Setup (`--remote-scope all` unless stated) | Expect |
|---|---|---|
| S1 | Remote `fix/foo` at a closed, unmerged PR's `head.sha` | REAPED `pr-closed where=remote`, and the remote ref is gone |
| S2 | Remote `feat/bar` at a merged-into-main PR's `head.sha` | REAPED `pr-merged where=remote` |
| S3 | Remote `main`, `audit-log`, `release/0.5.x` and `audit/x`, all ancestors of `origin/main` | Each is KEEP `protected-name`, and all four still exist on the remote |
| S4 | Remote `docs/wip` with unlanded content and no PR | KEEP `unlanded-no-pr`, and the ref still exists |
| S5 | Remote `docs/done` with no PR, whose content is squash-landed on main (one case for an ancestor, one for content) | REAPED `landed-ancestor`; REAPED `landed-content` |
| S6 | Default scope (no flag) with remote `fix/foo` at a closed PR head plus a reapable `worker-*` head | `fix/foo` gets no output line and is untouched. The `worker-*` head is reaped as today. A fake `remote_heads` records the pattern `refs/heads/worker-*` |
| S7 | `--dry-run` with S1–S5's heads | WOULD-REAP and KEEP lines only. The remote ref set is byte-identical before and after, and `remote_delete` is never called |
| S8 | Remote `fix/open` that is the head of an open PR and also of a closed PR (and a second case where it is landed) | KEEP `open-pr` |
| S9 | Remote `fix/x` whose PR becomes open only in the pre-delete re-check | KEEP `open-pr`, and the ref still exists |
| S10 | Non-worker reapable heads, with a counting `issue_states` | `issue_states` is never called (D2 does not apply) |
| S11 | `all` scope, fake `remote_heads` | It receives exactly `refs/heads/*`. A slashed name (`a/b/c`) from the real bare repo is listed |
| S12 | CLI: `--local-only --remote-scope all`; `--remote-scope bogus`; `reap_orphans(remote_scope="x")` | Exit 2 and nothing deleted; argparse exit 2; `ValueError` |
| S13 *[architect]* | `all` scope with a remote `worker-<n>-x` head whose issue and every commit-referenced issue are closed (no PR), plus one whose issue is open | Identical to the default scope: REAPED `issue-closed where=remote`; KEEP `unlanded-open-issue`. Widening the listing must not change worker-head decisions |
| S14 *[architect]* | `all` scope, fake `remote_heads` returning a name starting with `-` and a non-ASCII name | KEEP `unsafe-name`, the printed name is percent-encoded, and neither name reaches any `git` argv (recording `git` runner) or `remote_delete` |

## 7. Files

| File | Change |
|---|---|
| `scripts/automation/readopt.py` | `remote_scope` parameter, the pattern choice and conditional name filter, argparse flag and conflict check, docstrings |
| `tests/automation/test_readopt.py` | S1–S14 |
| this TD | |

## 8. Risk

- **RISK: MEDIUM.** `all` can delete a remote head pushed by another role or by a human, for example a `fix/*` branch. This is mitigated by:
  - the same rules as today: an open PR always wins, unlanded content without a covering closed or merged PR is only reported, and the protected names are never touched;
  - the 7-day grace, the open-PR re-check and the per-ref compare-and-swap;
  - recovery for PR-backed deletes through `refs/pull/N/head`.
- **Authorization:** the human authorized this in #2285 and #2288.
- **Residual: grace uses the commit date.** A human who pushes an old, already-landed commit under a new name can have it reaped immediately. The content is on main by definition (D3), or in `refs/pull/N/head` (D1 and D1'), so nothing is lost.
- **Residual *[architect]*: long-lived integration branches.** The never-touch list is the fixed HOS set (`main`, `audit-log`, `release/*`, `audit/*`). Under `all`, a long-lived non-PR-scoped branch such as `develop` or `staging` is reapable: D1 fires after a merged `develop`→`main` PR whose head covers the tip, and D3a fires whenever the branch is an ancestor of `main`. Nothing is lost (content is on `main` or in `refs/pull/N/head`), but the branch disappears. HOS's own remote has no such branch (#2288 acceptance), so this slice accepts it, gated by the opt-in flag and the human-reviewed dry-run below. **Binding on the later cron-wiring slice:** before `--remote-scope all` runs unattended, the protected set must either also cover the remote's default branch (`ls-remote --symref <url> HEAD`, fail-closed) and a configurable extra list, or the slice must record a human ruling that the fixed list suffices. The `--remote-scope` help text states that the never-touch list is fixed.
- **First run:** the first real `all` run must be preceded by a human-reviewed `--dry-run` from the Worker clone, attached to the PR, as TD-2286 §9.1 requires.
- **Opt-in only:** slice 1 wires nothing into cron, and the default scope is unchanged.
- **CONFIDENCE: HIGH** on the listing behaviour (verified empirically) and on D2 not applying to non-worker names (read in `_decide_rest`, `_WORKER_RE`).
