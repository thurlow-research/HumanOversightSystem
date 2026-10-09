# TECHNICAL DESIGN — #1856: closing-keyword guard in `submit_pr.sh`

Status: Architect APPROVED WITH CONDITIONS C1–C5, applied in-document (§11a) · Change class: **additive** · Author: technical-design

RISK: MEDIUM — changes a shared PR-opening path used by all three bot identities; a defect either blocks every PR (false refusal) or silently fails open.
CONFIDENCE: HIGH on contract; MEDIUM on GitHub's exact grammar edges (resolved conservatively, see §3).

## Human Review Required
- `bootstrap/submit_pr.sh`, `.claude/agents/worker.md`, `bootstrap/worker-cron-prompt.md`, `CLAUDE.md` are protected surfaces → human gate at merge (unchanged).
- No open human questions block coding; safe defaults are recorded in §8.

## 1. Problem
A PR title, body, or commit message that *quotes* a closing-keyword sentence (e.g. a verbatim ruling "S2 is the fix that closes #1539.") closes that issue on merge. PR #1725 silently closed critical #1539 this way. `bootstrap/submit_pr.sh` is the sanctioned PR path and detects nothing.

## 2. Prior-art search (required by CLAUDE.md item 1)
Searched `scripts/` (recursive), `bootstrap/`, `bin/`, `scripts/automation/lib/` for closing-keyword detection (`closing.?keyword`, `close[sd]?:?\s+#`, `fixes #`). **Found nothing** (only hits: prose "Fixes #1683" in `vendor_invoke.sh`'s header and a fixture file — neither detects anything). New module required.

## 3. Grammar (normative)
Scan with Python `re`, `IGNORECASE`, over the **whole text** (not per line), so a keyword at end-of-line followed by a ref on the next line is caught. Report the 1-based line of the keyword's first character.

```
KEYWORD = (?<![A-Za-z0-9_])(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)(?![A-Za-z0-9_])
SEP     = \s*:?\s*                      # zero-or-more whitespace incl. newline, optional colon
REF     = #(\d+)                                                     -> same-repo N
        | GH-(\d+)                                                   -> same-repo N
        | ([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)#(\d+)                  -> owner/repo#N
        | https?://github\.com/([^/\s]+)/([^/\s]+)/(?:issues|pull)/(\d+)  -> owner/repo#N
CHAIN   = (?:\s*(?:,|&|\band\b)\s*REF)*  # further refs joined by ',', '&', or 'and'
```
Match = `KEYWORD SEP REF CHAIN`. Every ref in the chain is a match (each at its own line). [Architect C2] GitHub documents one keyword per issue ("Closes #1, closes #2"), so "Closes #1, #2" probably closes only #1 — but that is an unverified grammar edge, and §3's own rule is to flag when in doubt. Chained refs are therefore flagged; a false refusal costs one rephrase or one extra `--closes`.

[Architect C1] The trailing `(?![A-Za-z0-9_])` on KEYWORD stops `fixtures/foo#12` or `fixesGH-5` from matching as `fix`+owner/repo ref / `fixes`+`GH-5`. `closes#5` still matches, because `#` is not a word character.

Conservative choices (flag when in doubt — a false refusal costs one rephrase; a miss costs a silently closed issue):
- `closes#5` (no space) **matches**. `re-fixes #3` **matches** (hyphen is a boundary).
- `prefixes #12`, `unfixed #3`, `fix_closes #4` do **not** match (letter/digit/underscore before keyword).
- **No exemptions** for code spans, fences, blockquotes, HTML comments. Rationale: a blockquoted ruling is the exact #1725 incident, and a squash-merge commit message carries title/body text with no markdown rendering at all.
- Title is scanned because squash-merge uses it as the default-branch commit subject.

Normalization (the key compared against `--closes`): same-repo refs → bare `N` (decimal, leading zeros stripped). A cross-repo ref whose `owner/repo` equals the PR repo slug case-insensitively → bare `N`. Any other repo → `owner/repo#N` lowercased. Cross-repo refs **must be declared** too (merge closes them if the bot has access).

## 4. Module: `scripts/automation/closing_keywords.py`
Placement follows the thin-wrapper precedent (`bootstrap/merge_authority.sh` → `scripts/automation/merge_authority_cli.py`; `submit_pr.sh` already reaches into `$SCRIPT_DIR/../scripts/oversight/lib/`). `submit_pr.sh` is not in the consumer ship-set today (`framework_consumer_files.txt`), so it always runs from a full HOS tree. **Stdlib only** (no venv dependency); interpreter is `python3` from PATH, already a hard dependency of `get_app_token.sh`.

Public API (unit-tested directly):
- `find_closing_refs(text: str, repo_slug: str) -> list[Match]` — `Match(key: str, line: int, snippet: str)`; `snippet` = the matched line, stripped, truncated to 120 chars.
- `parse_declared(values: list[str], repo_slug: str) -> set[str]` — each value is comma-split; each item must match `^\d+$` or `^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\d+$` (else `ValueError`); normalized per §3.
- `read_commits(repo_dir: str, rev_range: str) -> list[tuple[sha, message]]` — runs `git -C <repo_dir> log -z --format=%H%n%B <rev_range>` via `subprocess` (no shell); records NUL-separated, first line = full SHA. Non-zero git exit → raise.

CLI: `python3 closing_keywords.py check --repo-slug <owner/repo> [--closes <list>]... [--title <text>] [--body-file <path>] [--repo-dir <dir> --range <rev-range>] [--warn-unused]`
- `--closes` repeatable; values accumulate. `--repo-dir` and `--range` must be given together.
- Sources scanned: title (source label `title`), body (`body line N`), each commit (`commit <sha7> line N`, line 1 = subject).
- **Exit 0**: every match's key ∈ declared. If `--warn-unused`, each declared key with no match → one stderr warning line (`--closes N declared but no closing keyword for it found`), exit still 0.
- **Exit 1**: ≥1 undeclared match. stdout = exactly one line, the sorted unique undeclared keys comma-joined (for the audit event). stderr = the report in §6.
- **Exit 2**: usage error, invalid `--closes` item, unreadable body file, git failure. stderr one line. Never prints a partial verdict.

## 5. `bootstrap/submit_pr.sh` changes
1. **Arg**: add `--closes <list>` (repeatable; accumulate into a bash array `CLOSES_ARGS+=(--closes "$2")`). Valid in both open and `--update-pr` modes. Add to the usage `err` line and the header Usage block. [Architect C3] Initialize `CLOSES_ARGS=()` and always expand it as `${CLOSES_ARGS[@]+"${CLOSES_ARGS[@]}"}`. Under `set -u`, a bare `"${CLOSES_ARGS[@]}"` on an empty array aborts on bash < 4.4 (macOS /bin/bash 3.2) — and the empty array is the common case. `edit_issue_edges.sh` and `query_issues.sh` already use this idiom.
2. **Prereq resolution** (local, fail-closed): `CK_PY="$SCRIPT_DIR/../scripts/automation/closing_keywords.py"`. Missing file or no `python3` on PATH → `err` naming the missing piece ("closing-keyword guard unavailable — refusing to open a PR (#1856)"). Applies to all `--app` roles.
3. **Move** the existing "Resolve owner/repo from the origin remote" block (local `git remote get-url`) up to immediately after the branch-ownership block. No behavior change.
4. **Phase 1 — text scan** (open mode only; pre-network): immediately after step 3, before `git fetch`: run `check --repo-slug "$REPO_SLUG" "${CLOSES_ARGS[@]}" --title "$TITLE" --body-file "$BODY_FILE"`. Exit 1 → audit (§7, `phase":"text"`) then `err` with the summary line; exit 2 → `err`. stderr report from Python passes through to the caller unmodified.
5. **Phase 2 — full scan** (both modes): after the #1162 merge-from-base block, before token mint: run `check --repo-slug "$REPO_SLUG" "${CLOSES_ARGS[@]}" --repo-dir "$SCRIPT_DIR/.." --range "origin/${BASE}..refs/heads/${HEAD}" --warn-unused` plus, in open mode only, `--title`/`--body-file` again (so `--warn-unused` sees all sources). Same exit handling, `phase":"full"`. The range excludes commits already on base; a #1162 merge commit ("Merge remote-tracking branch …") is scanned like any other and normally matches nothing. In `--update-pr` mode this re-scans commits pushed earlier — intended, idempotent; callers re-pass the same `--closes`.
6. Under `set -euo pipefail`, capture the exit code explicitly (`rc=0; out="$(...)" || rc=$?`); any rc other than 0/1 is treated as 2 (fail closed).
7. No bypass flag other than `--closes`. `--confirmed` does not bypass. Identity-independent: worker, overseer, human all scanned.

## 6. Refusal report (stderr, from Python)
```
✘ submit_pr.sh: text would close issue(s) not declared with --closes (#1856):
  #1539   body line 60: "H6 — yes. S2 is the fix that closes #1539."
  o/r#7   commit 1a2b3c4 line 3: "fixes o/r#7"
Merging this PR would close the issue(s) above. If that is NOT intended, rephrase
(e.g. "the fix for #1539", "addresses #1539", or quote as "c-loses #1539"); for
commit messages, amend/reword the commit. If it IS intended, pass --closes 1539.
```
Display key: bare keys rendered `#N`; cross-repo keys as-is. One line per match (a key matched in two places prints twice).

[Architect C4] Append one more fixed line to the report whenever a commit source matched: "If the commit is already pushed (an --update-pr branch), it cannot be reworded without a force-push, which submit_pr.sh never does. Do NOT pass --closes for an issue you do not intend to close — escalate to a human to rebuild the branch." This is the only exit from the update-mode deadlock: an already-pushed commit that predates the guard or arrived by another route. Without it, the remedy the report offers — `--closes` — is a false declaration that would close the issue.

## 7. Audit
New best-effort helper `_hos_audit_closing_keyword_refusal <head> <base> <app> <phase> <keys>`, same shape and guarantees as `_hos_audit_stale_base_merge` (missing/failing sink never masks the refusal; always returns 0). Event JSON: `{"event":"closing-keyword-refused","branch":…,"base":…,"app":…,"phase":"text|full","refs":"<comma-joined keys>","timestamp":…}`, all strings through `_hos_pr_json_escape`. Emitted only on exit 1, before `err`.

## 8. Decisions recorded (safe defaults)
- D1 No matches + no flag → proceed silently (no `--closes none` required).
- D2 Declared but not matched → warning only (phase 2), never a failure.
- D3 `--closes` accepted with `--update-pr`; update mode scans commits only (PR body already exists and is not re-read).
- D4 Over-matching per §3 accepted; remedy is rephrasing. No allowlist file, no inline suppression marker (a marker would itself be quotable).
- D5 Out of scope: `post_comment.sh` (comments never close issues); PR-body edits via `edit_issue.sh` after open (tracked as a residual — see §11); shipping `submit_pr.sh` to consumers.

## 9. Doc updates (all protected surfaces)
- `bootstrap/submit_pr.sh` header: Usage gains `[--closes <n>[,<n>...]]` in both forms; new paragraph describing the guard, grammar summary, no-exemption rule, and #1725/#1539 provenance.
- `bootstrap/worker-cron-prompt.md` Step 5 (~L138-140): usage line gains `[--closes <n>]`; add one sentence: "It refuses if the title, body, or any branch commit message contains a closing keyword (`closes/fixes/resolves #N`, any tense) for an issue not passed in `--closes` — when quoting a ruling, rephrase rather than quote the keyword."
- `.claude/agents/worker.md` L130 table row: add `[--closes <n>[,<n>...]]` to both forms; L383 Step 9: append the same one-sentence rule.
- `CLAUDE.md` "What to do instead" item 5: after the `submit_pr.sh --app human requires --confirmed` sentence add "`submit_pr.sh` also refuses undeclared closing keywords in the title/body/commits; pass `--closes <n>` only when the PR genuinely closes that issue (#1856)."

## 10. Test plan
**A. `tests/automation/test_closing_keywords.py`** (pure unit, import module):
1. Each of the 9 keywords × lower/UPPER/Title case → match.
2. Colon forms: `Closes: #5`, `closes :#5`; no-space `closes#5`; newline between keyword and ref.
3. Ref forms: `#5`, `GH-5`, `o/r#5`, `https://github.com/o/r/issues/5`, `…/pull/5`; same-repo slug (any case) normalizes to `5`; other repo → `o/r#5`.
4. Negatives: `prefixes #12`, `unfixed #3`, `fix_closes #4`, `closes the bug in #9` (words between), `#5 is closed`, bare `#5`.
5. Ref chains (C2): `Closes #1, #2` → `{1,2}`; `fixes #1 and #2` → `{1,2}`; `closes #1 & o/r#3` → `{1,o/r#3}`; `closes #1 and fixes #2` → `{1,2}`; `closes #1 see #2` → `{1}`. Trailing boundary (C1): `fixtures/foo#12`, `fixesGH-5` → no match; `closes#5` → match.
6. No exemptions: inside backticks, inside a ```` ``` ```` fence, inside `> ` blockquote, inside `<!-- -->` → match.
7. **#1725 fixture**: a 60+-line body whose line 60 is `> H6 — yes. S2 is the fix that closes #1539.` → key `1539`, line 60.
8. `parse_declared`: `"1539,12"`, repeated values, `o/r#7`, same-repo `owner/repo#5`→`5`, invalid items (`abc`, `#5`, `5,`, empty) → ValueError.
9. CLI exit codes 0/1/2, stdout single sorted line on 1, `--warn-unused` warning, `--repo-dir` without `--range` → 2, git failure → 2.
10. `read_commits` against a real temp git repo (two commits, one with a keyword in the body line 3) → correct sha/line.

**B. `tests/automation/test_submit_pr.py`** — harness changes: copy `scripts/automation/closing_keywords.py` into `tmp/scripts/automation/`; git stub gains `log) [[ -n "${GIT_LOG_FILE:-}" ]] && cat "$GIT_LOG_FILE" ;;` (default empty → zero commits, so every existing test is unchanged). New tests:
1. #1725 fixture body, no `--closes` → exit 1, stderr names `#1539` and `body line 60`; `_assert_fully_refused_before_network`.
2. Title `fix: closes #42` → refused pre-network, stderr `title`.
3. Clean body, `GIT_LOG_FILE` with `fixes #77` in a commit body → refused after fetch, no token mint, no push; stderr `commit <sha7>`. (C5) Assert ordering from the capture log: the `fetch` call precedes the `log` call, and the `log` call's range argument is exactly `origin/main..refs/heads/<head>`.
4. Same as 1 with `--closes 1539` → PR created.
5. No keywords, no flag → PR created (equals existing happy path).
6. `--closes 99`, no matches → PR created, stderr warning.
7. `--update-pr` with keyword commit → refused before token mint; with `--closes` → pushes.
8. Applies to `--app overseer` and `--app human --confirmed` (one refusal test each).
9. Refusal emits `closing-keyword-refused` audit event; audit sink failure does not mask refusal.
10. Module missing from `tmp/scripts/automation/` → fail-closed `err`, no push.
11. Invalid `--closes abc` → exit non-zero, no network.
12. (C5) Phase-2 fail-closed: the git stub's `log)` branch honors `GIT_LOG_FAIL=1` (exit 1). This must refuse with no token mint and no push. A failing `git log` must never read as "zero commits".
13. (C3) A happy path with no `--closes` must pass under `set -u` — test 5 already covers this. Where a bash 3.2 binary is available, also run test 5 under it (skip if absent).

## 11. Residuals (not built here; for the worker to file if architect agrees)
- PR body edited after open (`edit_issue.sh --body-file` on a PR, or GitHub UI) bypasses this guard.
- Squash-merge commit message composed at merge time by `merge_authority`/overseer is not scanned.

## 11a. Architect review record (2026-10-09)
Verdict: APPROVED WITH CONDITIONS. The architect applied C1–C5 directly to this TD:
- C1 §3 — trailing word boundary on KEYWORD.
- C2 §3, §10.A5 — flag ref chains (`, & and`) conservatively.
- C3 §5.1, §10.B13 — bash-3.2-safe empty-array expansion.
- C4 §6 — update-mode remedy line (escalate; never pass a false `--closes`).
- C5 §10.B3/B12 — phase-2 ordering assertion and `git log` failure fail-closed test.

Verified: `submit_pr.sh` and `scripts/automation/` are absent from `scripts/framework/framework_consumer_files.txt` and from `hos_install.sh`'s explicit `bootstrap/` copy list, and `hos_install.sh` rsyncs only `scripts/oversight/`. The script therefore always runs from a full HOS tree, so the `$SCRIPT_DIR/../scripts/automation/` path is sound. The shipped `worker.md` and `worker-cron-prompt.md` already name `submit_pr.sh`, so adding `--closes` to their prose adds no new consumer gap.

## 12. Startup-gap analysis
Not a reactive correction to an existing design contract (new guard on an unchanged contract). No prior sign-offs affected.
