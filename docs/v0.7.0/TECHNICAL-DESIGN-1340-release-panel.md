# TECHNICAL DESIGN — #1340 PR 1: the release panel as an edge-parameterised mode, and a verdict that is recomputed rather than read

**Status:** DRAFT-1 — awaiting `architect` review (iteration 1 of a 5-round cap). Implementation contract for
`docs/v0.7.0/ADR-1340-release-panel.md` **PR 1 only** (ADR §2 AD-9, first table). Contains no application code.
**Date:** 2026-09-14
**Author:** technical-design
**Baseline:** working tree at `0b86aa52b318959f629ff39656738cd785860a76` (= `origin/main` in this clone).
Every line number below was re-derived from the working-tree blob this session (§0), not copied from the ADR.
**Consumes:** ADR-1340 (AD-1..AD-9, BINDING); issue #1340's pm-agent requirements comment (REQ-A1..A13, §9 AC 1–16).
**Consumer:** `coder`, then `unit-test`.
**Scope:** PR 1. Does **not** touch `.claude/agents/worker.md`, `.claude/agents/overseer.md`, `token_tracker.py`,
or the shallow-clone remediation (#1630). PR 1 is deliberately inert: nothing invokes the new suite.

---

## 0. Verification — the ADR's anchors, re-derived against the real tree

`scripts/run_panel.sh` is **785 lines**. Every line reference in ADR §0 and §2 was checked. **All of them hold
exactly or within ±1 line**, which is unusual and worth stating plainly so `coder` can trust the ADR's map:

| ADR cites | Real | Verified content |
|---|---|---|
| `:214-219` PR + `HEAD_SHA` | `:213-220` | `gh pr view --json number` / `headRefOid` / `title` |
| `:223` ledger path | `:223` | `PANEL_LEDGER=".ai-local/panel/pr${PR}-ledger.jsonl"` |
| `:249-253` run dir + diff | `:249-253` | `RUN_DIR=".ai-local/panel/pr${PR}-<ts>"`, `gh pr diff` ×2 |
| `:291-297` floor ∪ trailer | `:291-297` | `triage-floor`, then `AI-Risk:` scan over `gh pr view --json commits` |
| `:335-362` SQC | `:335-362` | salt, `sqc-sample`, `sample-log.jsonl` |
| `:348-350` SQC keyed on head | `:348-350` | `--head-sha "$HEAD_SHA"` |
| `:365-372` LOW skip | `:365-372` | `rank < 1` → `exit 0` unless `SAMPLED` |
| `:387-714` engine | `:387-714` | chunking → fan-out → arbiter → salvage → rank → `render-tier` |
| `:475-476` / `:483-486` fail-closed | identical | `die` on missing reviewer / failed invocation (#682) |
| `:544-554` arbiter salvage | identical | `reconcile-arbiter`, `ARBITER_SALVAGED` (#978) |
| `:655-659` `post_thread` | `:655-659` | `gh api .../pulls/$PR/comments` with `commit_id="$HEAD_SHA"` |
| `:700-705` → `:735-737` unanchored | identical | the degradation that seeded release mode |
| `:726-731` tier order | identical | Tier 1 section before Tier 2 |
| `:743-745` IP caveat | identical | placeholder-agent warning |
| `:767-769` `panel-verdict.json` | `:765-769` | `printf` of the SPEC-78 verdict |

Also confirmed: `run_review_chain.sh:109-152` is `autodetect_files` and carries the `HEAD~1` fallback at
`:127-132`; `run_review_chain.sh:288-292` skips the panel without `--pr`; `.ai-local/` is `.gitignore:3`;
`grep -n panel scripts/oversight/token_tracker.py` is empty (AF-3 holds).

### TD-VF-1 (CORRECTION to AF-1 — the mechanism is misattributed; the conclusion survives and worsens)

AF-1 says `run_validators.sh:349` "performs the same derivation" and is "today scoring one commit". Measured:

```
scripts/oversight/run_validators.sh:345-353   # the actual chain
  1. origin/main present? -> DS_BASE_REF = git merge-base HEAD origin/main
  2. else                 -> DS_BASE_REF = git describe --tags --abbrev=0     <- :349
  3. else                 -> DS_BASE_REF = HEAD~1
```

`git rev-parse origin/main` → `0b86aa52`, `git merge-base HEAD origin/main` → `0b86aa52` = **HEAD**.
Branch 1 wins, so `:349` never runs and `DS_BASE_REF == HEAD`; `git diff --numstat HEAD` yields **zero
changed lines**. The R2 row `scripts/oversight/run_validators.sh (diff since last tag)` (`worker.md:648`) is
therefore not scoring one commit — in this clone its diff-size dimension scores **an empty range**. The
`HEAD~1` degeneracy AF-1 describes is real but lives in `run_review_chain.sh:127-132`, not there.

AF-1's *conclusion* is unaffected and slightly stronger: the currently-required "diff since last tag" R2 row
does not review the release range in this clone. **AD-2 is unchanged** — the release panel refuses rather
than inherits, whichever degeneracy applies. This correction belongs in FU-3's framing, not in PR 1's code.
Recorded here rather than silently fixed; `architect` is notified.

### TD-VF-2 (closes the ADR §0 "verification gap" on tag reachability)

```
git rev-parse --is-shallow-repository  -> true
git rev-list --count HEAD              -> 19          (grafted depth)
git rev-parse v0.6.0^{commit}          -> 7b1220e4…   (object PRESENT)
git rev-parse v0.5.0^{commit}          -> fda041ff…   (object PRESENT)
git merge-base --is-ancestor v0.6.0 HEAD -> NO
```

The tag objects resolve to real commits in this clone; only *ancestry* is missing. That is the signature of a
shallow graft, **not** a rewritten history — a rewrite would leave the tags pointing at objects absent or at
commits with unrelated trees. So ESC-1 option (a) (`git fetch --unshallow --tags`) is very likely sufficient
and the remediation does **not** grow. This cannot be proven without actually unshallowing (network write,
out of scope here), so it is stated as strong evidence, not proof. **No PR 1 code depends on the answer.**

### TD-VF-3 (CORRECTION to AD-1 — "nothing between :387 and :714 changes" is false at two places)

Two lines inside the declared-untouchable engine region must change. Both are additive and neither alters
control flow, but the ADR's claim as written is not implementable:

1. **`:448`** — `PANEL_ADVISORY_FILE=".claudetmp/panel/advisory-pr${PR}-$(date …)"`. PR-bound, inside the
   engine. (ADR §0's grep missed it because the expansion is `${PR}`, which `\$PR` does not match.)
   Resolution: §3.1 introduces `RUN_LABEL`, computed once in the identity edge; `:448` becomes
   `advisory-${RUN_LABEL//\//-}-…`. Mode-invariant afterwards.
2. **`:481-493`** — AD-7 mandates a `chunks_attempted == chunks_completed` check, and the engine tracks
   neither. Two counter increments must be added inside the reviewer fan-out loop (§3.5). They are
   incremented in **both** modes (only release mode reads them), so the engine keeps one behaviour.

`coder` must treat these as the *only* two permitted edits between `:387` and `:714`. Everything else in that
span is off-limits.

### TD-VF-4 (GAP in AD-1 — there is a sixth PR-bound edge: the SPEC-78 ledger)

AD-1's table names five edges. A sixth exists and is unenumerated: the per-PR ledger and everything keyed on
it — `:223` (`PANEL_LEDGER`), `:229-247` (`--record`/`--reset`), `:588-618` (`NEW_BLOCKING_COUNT`),
`:628-650` (`LEDGERED_FLAGS`), `:667-689` (thread suppression), `:768` (verdict field). In release mode `$PR`
is empty, so `PANEL_LEDGER` would resolve to `.ai-local/panel/pr-ledger.jsonl` — a **shared, cross-release
ledger** — and a tier-1 finding ledgered during any earlier run would be suppressed.

Resolution (§3.6): **release mode disables the ledger entirely.** Derived from AD-5 and AD-7, not invented:
AD-5 removes thread posting, which is the only thing suppression suppresses; AD-7 requires
`findings.tier1_undispositioned == 0`, and a ledger-suppressed tier-1 finding is by construction an
undispositioned finding that would not be counted. Flagged to `architect` as an addition to AD-1's table.

### TD-VF-5 (GAP in AD-7 — `query_issues.sh --comments` output is author-spoofable)

AD-7 §2 says "read comments via `bootstrap/query_issues.sh --app worker --comments <n>`; filter to those
authored by the worker bot identity". Real output format (`bootstrap/query_issues.sh:205-206`):

```
gh api ".../issues/<n>/comments?per_page=100" --jq '.[] | "--- \(.user.login) @ \(.created_at) ---\n\(.body)\n"'
```

Author and body are concatenated into one untyped text stream with a `--- <login> @ <ts> ---` delimiter, and
**the body is interpolated verbatim**. Any commenter — human or bot, with no special permission — can write a
comment whose body contains the literal line `--- hos-worker-hos[bot] @ 2026-01-01T00:00:00Z ---` followed by
a fenced verdict block. A text parser attributes that block to the worker. AD-7's identity bound is the only
control standing between "an artifact posted by the worker" and "an artifact anyone can post", so this is not
a cosmetic parsing nit: it removes the one bound the ADR's own residual-risk paragraph relies on.

Resolution (§2.4): add a `--comments-json` mode to `bootstrap/query_issues.sh` emitting one compact JSON
object per line (`{"user":…,"created_at":…,"body":…}`, jq-escaped, so no delimiter can be forged from inside a
body). `--verify` uses that mode; the existing `--comments` text mode is untouched.

**This adds a 12th file to AD-9's PR 1 table.** It is a ~4-line additive change to an existing canonical entry
point (D41-compliant — no second GitHub reader), but it is a scope change to a BINDING table and `architect`
must acknowledge it. `coder` must not start until that acknowledgement lands.

### TD-VF-6 (interpretation of "no subprocess CLI calls")

AD-9's row 1 says `release_panel_logic.py` is "Pure Python, no subprocess CLI calls". Read literally this makes
AD-2 unimplementable — range derivation *is* a set of git queries. Reading taken: **no vendor-CLI calls**
(`agy`, `codex`, `claude`, `gh`). `git` is permitted and is confined to a single injectable seam (§1.2
`run_git`) so that every function above it is pure and unit-testable without a repository. `gh` never appears
in this module; all GitHub I/O goes through `bootstrap/` wrappers called from the shell. Flagged for
`architect` confirmation; if the stricter reading is intended, AD-2 needs a different home.

### Searched-first (CLAUDE.md item 1)

Searched `scripts/`, `bootstrap/`, `bin/`, `scripts/automation/lib/` for existing range derivation, glob
matching, and comment reading before specifying anything new:
- **Found and reused:** `scripts/framework/require_human_approval.py:41-92` — `load_globs`, `glob_to_regex`,
  `matched_surfaces`. Import-safe (only `SURFACES_FILE` at module scope, `__main__`-guarded). §1.4 reuses it
  rather than writing a second glob matcher.
- **Found, not applicable:** `scripts/oversight/lib/step_range.sh` — step ranges from the audit log, not tags.
- **Found, deliberately not reused:** `run_review_chain.sh:109-152` `autodetect_files` — it is bash, it feeds
  validators, and AD-2 requires the three refusals it lacks. AD-2 mandates same *semantics*, new *home*.
- **Found nothing** for: post-exclusion file digests, verdict composition, verdict verification.

---

## 1. `scripts/oversight/release_panel_logic.py` — module contract

Pure logic + one git seam. Importable as `import release_panel_logic` from `tests/` (`tests/conftest.py`
already puts `scripts/oversight` on `sys.path`). Also an argparse CLI so the two shell scripts can call it.

### 1.1 Constants

```
EXCLUSIONS_PATH_DEFAULT = "scripts/oversight/release_panel_exclusions.txt"
VERDICT_ARTIFACT        = "hos-release-panel-verdict"
VERDICT_SCHEMA_VERSION  = 1
VERDICT_MARKER          = "<!-- hos-release-panel-verdict v1 -->"
DERIVATION              = "since-tag"
```

### 1.2 The git seam — the only subprocess in the module

```
run_git(args: list[str], *, cwd: str = ".") -> tuple[int, str, str]
```
Returns `(returncode, stdout_stripped, stderr_stripped)`. Never raises on non-zero. **Every** git call in this
module goes through it; tests monkeypatch this one function. No other function in the module may call
`subprocess`.

Thin wrappers, each one `run_git` call:
```
is_shallow(cwd=".") -> bool                     # git rev-parse --is-shallow-repository == "true"
latest_tag(cwd=".") -> str | None               # git describe --tags --abbrev=0; None on non-zero/empty
rev_parse(rev, cwd=".") -> str | None           # git rev-parse --verify --quiet <rev>
changed_files(base, head, cwd=".") -> list[str] # git diff --name-only <base> <head>   (TWO-dot)
```

`changed_files` uses the **two-argument** form, byte-identical in semantics to `run_review_chain.sh:135`
(`git diff --name-only "$base" "$head"`) and to AD-7's `base..head`. Three-dot is **forbidden** — it would
silently change what "the release range" means between the runner and the verifier.

### 1.3 `RangeResult`

```
@dataclass(frozen=True)
class RangeResult:
    state: str            # "OK" | "SHALLOW" | "NO_TAG" | "NO_CONTENT"
    base_ref: str | None  # e.g. "v0.6.0"; None unless resolved
    base_sha: str | None  # 40 hex; None unless resolved
    head_sha: str | None  # 40 hex; None unless resolved
    derivation: str       # always "since-tag"
    files_in_range: int   # 0 unless the diff was taken
    files_excluded: int
    reviewed: tuple[str, ...]   # sorted, post-exclusion
    excluded: tuple[str, ...]   # sorted
    reason: str           # "" when OK; else a stable slug (see below)
    remediation: str      # "" unless SHALLOW
```

Reason slugs (stable strings — R3's excerpt names the cause, so they must not be reworded casually):
`"range-derivation-failed: shallow clone"`, `"range-derivation-failed: no tag reachable from HEAD"`,
`"range-derivation-failed: base sha unresolvable"`, `"NO-CONTENT: zero files after exclusions"`.
`remediation` for SHALLOW is the literal string `"git fetch --unshallow --tags"`.

`"range-derivation-failed: base sha unresolvable"` is a fifth internal condition (tag resolves but
`rev-parse <tag>^{commit}` fails, or `rev-parse HEAD` fails). It maps onto the **`NO_TAG`** state — it is not a
fifth public state; AD-2 fixes four, and `coder` must not add one.

### 1.4 `derive_range` — the single implementation, called by BOTH modes

```
derive_range(*, cwd: str = ".",
             exclusions_path: str = EXCLUSIONS_PATH_DEFAULT) -> RangeResult
```

Order is normative and must not be reordered (a SHALLOW clone also fails `git describe`, so the precedence
determines which reason the operator sees):

1. `is_shallow(cwd)` → `RangeResult(state="SHALLOW", reason=…, remediation="git fetch --unshallow --tags")`.
2. `tag = latest_tag(cwd)`; falsy → `state="NO_TAG"`. **No `HEAD~1` fallback exists anywhere in this module.**
3. `base_sha = rev_parse(f"{tag}^{{commit}}")`, `head_sha = rev_parse("HEAD")`; either falsy →
   `state="NO_TAG"`, reason `base sha unresolvable`.
4. `files = changed_files(base_sha, head_sha)`.
5. `reviewed, excluded = apply_exclusions(files, load_exclusions(exclusions_path))`.
6. `reviewed` empty → `state="NO_CONTENT"` (all other fields populated, so the caller can render coverage).
7. Otherwise `state="OK"`.

**Binding:** `run_release_panel.sh` execute mode and `--verify` mode both call this function and nothing else.
There is exactly one derivation. A second derivation anywhere in PR 1 is a defect, not a style choice.

### 1.5 Exclusions

```
load_exclusions(path: str) -> list[str]
```
Delegates to `scripts.framework.require_human_approval.load_globs` (imported by inserting the repo root on
`sys.path`, the `record_agent_model.py:39` idiom). A missing or unreadable exclusions file is **fatal**, not an
empty list: silently reviewing excluded files would change `files_digest` and break verification, and silently
reviewing *nothing* would be worse. Raise `FileNotFoundError`; the CLI turns it into exit 1.

```
apply_exclusions(files: list[str], globs: list[str]) -> tuple[list[str], list[str]]
```
Returns `(reviewed_sorted, excluded_sorted)`, both `sorted()` with Python's default (byte-wise) ordering.
Matching delegates to `require_human_approval.glob_to_regex` / `matched_surfaces` — **no second glob engine**
(D41). Paths are compared exactly as git emits them (repo-relative, forward slashes, no leading `./`).

```
exclusions_sha256(path: str) -> str
```
`hashlib.sha256` over the file's **raw bytes**, hex digest. Not over parsed globs — a comment edit changes the
hash, which is the intended "widening the list invalidates the run" property of AD-3.

```
files_digest(reviewed: list[str]) -> str
```
Normative formula, because runner and verifier must agree byte-for-byte:
```
payload = "".join(p + "\n" for p in sorted(reviewed))
digest  = sha256(payload.encode("utf-8")).hexdigest()
```
Empty list → digest of the empty string (`e3b0c442…`). Trailing newline after **every** entry including the
last. No separators, no JSON, no sorting locale.

### 1.6 Verdict composition

```
compose_verdict(*, range_result: RangeResult,
                panel: dict,              # parsed $RUN_DIR/panel-release.json (§3.7)
                exclusions_path: str,
                run_id: str,
                issue: int,
                panel_exit_code: int) -> dict
```

Returns the AD-4 object. Field names are **verbatim from AD-4 and may not be renamed or removed.** Additive
fields permitted by AD-4 and used here: `issue`, `panel_exit_code`, `verdict_reason`,
`coverage.exclusion_globs`, `risk.sqc`.

`result` is computed, never passed in:
```
PASS  iff  panel_exit_code == 0
       and coverage.files_reviewed == coverage.files_in_range - coverage.files_excluded
       and coverage.chunks_attempted == coverage.chunks_completed
       and findings.tier1_undispositioned == 0
       and arbiter_salvaged is False
NO-CONTENT  iff range_result.state == "NO_CONTENT"   (composed for the record; never PASS)
FAIL        otherwise
```
`verdict_reason` carries the first failing clause as a stable slug: `panel-exit-nonzero`,
`coverage-mismatch`, `chunk-shortfall`, `tier1-undispositioned`, `arbiter-salvaged`. `""` when PASS.
`completed_at` is `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` — second precision, `Z` suffix,
so `completed_at` string-sorts identically to its chronological order (the AD-7 §3 selection rule depends on
this; parse it for comparison, do not string-compare, but the format keeps the two consistent).

```
render_comment_body(*, verdict: dict, panel_summary_md: str) -> str
```
Composes the issue comment. Required structure, in order:
1. `## 🔭 Release panel — verdict` heading with `**Result:** PASS|FAIL|NO-CONTENT`.
2. `**Release candidate SHA:** <head_sha>` and `**Reviewed range:** <base_ref> (<base_sha12>)..<head_sha12>`
   — AC 2's literal requirement.
3. A **coverage paragraph in prose** (AD-4's explicit requirement — a human must see the coverage claim
   without parsing JSON): files reviewed / in range / excluded, chunks completed / attempted, and the
   exclusion globs applied, listed.
4. `panel_summary_md` verbatim — the body `run_panel.sh` already assembled (`:717-746`), which already carries
   Tier 1 before Tier 2 (`:726-731`) and the IP-placeholder caveat (`:743-745`).
5. `VERDICT_MARKER` on its own line, then a fenced ```json block containing
   `json.dumps(verdict, indent=2, sort_keys=True)`.

The marker must be on its own line immediately preceding the fence; the parser (§1.7) relies on that adjacency.
`render_comment_body` must never emit a body starting with `@/` (post_comment.sh's #1155 guard) — the fixed
heading guarantees this, and a test asserts it.

### 1.7 Verdict extraction, selection, verification

```
extract_verdicts(ndjson_text: str) -> list[dict]
```
Input is `--comments-json` output (§2.4): one `{"user","created_at","body"}` object per line. For each line:
`json.loads` (a malformed line is skipped, not fatal); scan `body` for `VERDICT_MARKER`; for each occurrence
take the next fenced ```` ```json ```` block; `json.loads` it (malformed → skip). Returns
`[{"user": …, "created_at": …, "verdict": {…}}]` in comment order. A single comment may carry more than one
block; all are returned.

```
select_verdict(candidates: list[dict], *, head_sha: str,
               author: str) -> tuple[dict | None, str]
```
AD-7 §3, exactly:
1. Keep entries where `entry["user"] == author` (exact string match, case-sensitive).
2. Keep entries where `verdict["range"]["head_sha"] == head_sha`.
3. **Select the newest by `verdict["completed_at"]`** (parsed as a datetime). Not the newest *passing* one —
   a stale PASS must not shadow a fresh FAIL at the same SHA. Ties: the later position in the input list wins
   (comments are returned in GitHub's chronological order).
4. Zero candidates → `(None, "verdict-missing")`.

`author` is required and must be non-empty; an empty author is a programming error, not "match anything".

```
@dataclass(frozen=True)
class CheckResult:
    name: str       # the AD-7 check name
    ok: bool
    expected: str
    actual: str

@dataclass(frozen=True)
class VerifyResult:
    result: str            # "PASS" | "FAIL"
    reason: str            # "" on PASS; else the first failing check's slug
    checks: tuple[CheckResult, ...]

verify_verdict(verdict: dict, *, range_result: RangeResult,
               exclusions_path: str, cwd: str = ".") -> VerifyResult
```

All ten AD-7 checks run — **every one of them, even after the first failure** — so the operator sees the full
picture in one pass; `reason` reports the first failure in table order. Four are recomputations; the
recomputed values come from `range_result` (already derived by §1.4) and from fresh hashing, **never** from
the verdict:

| # | `name` | Action | Failure slug |
|---|---|---|---|
| 1 | `schema_version` | literal `== 1` | `schema-version-mismatch` |
| 2 | `head_sha` | **recompute** `rev_parse("HEAD")`, compare to `range.head_sha` | `head-sha-mismatch` |
| 3 | `base_sha` | **re-derive** — compare `range_result.base_sha` to `range.base_sha` | `base-sha-mismatch` |
| 4 | `exclusions_sha256` | **re-hash** the committed file | `exclusions-hash-mismatch` |
| 5 | `files_digest` | **recompute** `files_digest(range_result.reviewed)` | `files-digest-mismatch` |
| 6 | `coverage_arithmetic` | `files_reviewed == files_in_range - files_excluded` | `coverage-mismatch` |
| 7 | `chunks` | `chunks_attempted == chunks_completed` | `chunk-shortfall` |
| 8 | `result` | `verdict["result"] == "PASS"` | `result-not-pass` |
| 9 | `arbiter_salvaged` | `is False` (strict — `"false"` the string fails) | `arbiter-salvaged` |
| 10 | `tier1_undispositioned` | `== 0` (strict int) | `tier1-undispositioned` |

A missing or wrong-typed field is a **failure of its own check**, never an exception and never a default.
`verdict.get("coverage", {}).get("chunks_attempted")` returning `None` fails check 7; it does not compare
`None == None` to True. Every numeric comparison coerces nothing: `2 == "2"` is a failure.

Also normative: check 3 is *not* "read `base_sha` and trust it". `range_result` is produced by §1.4 at
verification time. If §1.4 refused (SHALLOW/NO_TAG), `verify_verdict` is never reached — §2.3 step 1 turns the
refusal into a gate FAIL before any comment is read.

### 1.8 CLI surface (argparse; called only by the two shell scripts)

| Subcommand | Args | stdout | Exit |
|---|---|---|---|
| `derive-range` | `--exclusions <p>` `--cwd <p>` | `RangeResult` as JSON | 0 if `OK`, else 4 |
| `new-run-id` | — | a UUID4 string | 0 |
| `files-digest` | reads paths on stdin, one per line | the hex digest | 0 |
| `exclusions-sha256` | `--exclusions <p>` | the hex digest | 0 |
| `compose` | `--range-json <f> --panel-json <f> --exclusions <p> --run-id <s> --issue <n> --panel-exit <n> --out-verdict <f> --out-body <f>` | one summary line | 0 if `result == PASS`, 6 otherwise |
| `verify` | `--comments-json <f> --exclusions <p> --author <login> --cwd <p>` | `VerifyResult` as JSON | 0 PASS / 7 verdict-missing / 8 check failed |

`--help` on every subcommand. No subcommand writes to GitHub, spawns a vendor CLI, or reads `.ai-local/`
except as told by an explicit path argument.

---

## 2. `scripts/run_release_panel.sh` — the entry point

Thin. Owns derivation dispatch, delegation, verdict posting, and `--verify`. **Contains no review logic**:
no roster, no chunking, no reviewer dispatch, no finding rendering. If `coder` finds themselves writing any of
those here, the design has been misread.

### 2.1 CLI surface

```
scripts/run_release_panel.sh --issue <n> [--dry-run]
scripts/run_release_panel.sh --verify --issue <n> [--author <login>]
scripts/run_release_panel.sh --help
```

- `--issue <n>` — **required in both modes.** Execute: the release-request issue the comment is posted to.
  Verify: the issue whose comments are searched. Must be a positive integer.
- `--verify` — verification mode. **Never invokes `run_panel.sh`. Never invokes `agy`, `codex`, or `claude`.**
  A grep-level test asserts this (§5.4 T-S4).
- `--dry-run` — execute mode only. Runs the panel with `--dry-run` passed through, composes the verdict,
  prints the body to stdout, **posts nothing**. `--verify --dry-run` is a usage error (verify posts nothing
  anyway; accepting the flag would suggest otherwise).
- `--author <login>` — verify mode only. Resolution order: `--author`, then `$HOS_EXPECTED_BOT_LOGIN`, then
  the bot login recorded in `config.sh` if present. **Unresolvable → exit 1 with `author-unresolved`.**
  Fail-closed: never fall back to "accept any author", which would discard AD-7's only identity bound.

### 2.2 Execute mode

1. **Preflight.** `git`, `python3`, `jq` on PATH; `scripts/run_panel.sh`, `scripts/oversight/release_panel_logic.py`,
   `scripts/oversight/release_panel_exclusions.txt`, `bootstrap/post_comment.sh` all present. Any miss → exit 1.
2. **Derive** via `release_panel_logic.py derive-range`. Map the state to an exit and a stderr line, then stop:
   `SHALLOW` → exit 2, printing the reason **and the literal remediation** `git fetch --unshallow --tags`;
   `NO_TAG` → exit 3; `NO_CONTENT` → exit 4. **In this clone today, step 2 exits 2. That is correct behaviour
   (AD-2, ESC-1), not a bug for `coder` to work around.**
3. **Run id + run dir.** `RUN_ID=$(… new-run-id)`. Compute
   `RUN_DIR=".ai-local/panel/release/${HEAD_SHA}-$(date -u +%Y%m%d-%H%M%S)"` and export it as
   **`PANEL_RUN_DIR`**. `run_panel.sh` honours `${PANEL_RUN_DIR:-}` when set (§3.1) — an env-var seam, not a
   second flag, so AD-1's "gains one flag" holds. This is how the caller learns the run dir without parsing
   the engine's stdout.
4. **Delegate:** `bash scripts/run_panel.sh --release-range "${BASE_SHA}..${HEAD_SHA}"` (+ `--dry-run`).
   Capture the exit code as `PANEL_EXIT`; do **not** abort on non-zero — a non-zero panel is a FAIL verdict
   that must still be composed and posted, per REQ-A4/AC 4 ("produces FAIL, not a degraded PASS"). A panel
   crash so severe that `$RUN_DIR/panel-release.json` does not exist → exit 5 with `panel-artifact-missing`
   (nothing to attest; posting a verdict would be manufacturing evidence).
5. **Compose:** `release_panel_logic.py compose …` → `$RUN_DIR/verdict.json` and `$RUN_DIR/comment-body.md`.
6. **Post:** `bash bootstrap/post_comment.sh --number <n> --body-file "$RUN_DIR/comment-body.md" --app worker`.
   Never `gh api -f body=@path` (#1155). A post failure → exit 5 with `post-failed`: the verdict exists only
   in a gitignored dir (AF-4), so an unposted verdict has not crossed the clone boundary and does not exist
   for gate purposes.
7. **Exit** 0 if `result == PASS`, 6 if `FAIL`.

Note on `--dry-run`: the panel's `--dry-run` path (`:748-753`) prints instead of posting, which in release
mode is already a no-op (§3.6 — release mode never posts from `run_panel.sh`). `--dry-run` in release mode
therefore means only "do not call `post_comment.sh`". State that in `--help`.

### 2.3 Verify mode

1. **Derive** via §1.4. Any refusal → the **gate FAILs**, loudly, with that reason: `SHALLOW` → exit 2,
   `NO_TAG` → exit 3, `NO_CONTENT` → exit 4. A shallow clone must fail the gate, never silently pass a
   one-commit review (AD-7 step 1).
2. **Read** `bash bootstrap/query_issues.sh --app worker --comments-json <n> > "$TMP/comments.ndjson"`
   (§2.4). A read failure → exit 5 `comments-unreadable` (fail-closed: an unreadable thread is not a pass).
3. **Verify**: `release_panel_logic.py verify --comments-json … --author …`. Exit 0 / 7 / 8.
4. Print the ten checks, one line each, `PASS`/`FAIL` with expected-vs-actual, then the final status line.

### 2.4 `bootstrap/query_issues.sh` — new `--comments-json <n>` mode (the 12th file, TD-VF-5)

Additive, alongside the existing `--comments`:
```
gh api "repos/${REPO_SLUG}/issues/${N}/comments?per_page=100" --jq \
    '.[] | {user: .user.login, created_at: .created_at, body: .body} | tojson'
```
One compact JSON object per line. jq escapes the body, so no content inside a comment can forge a record
boundary or an author. Register it in the usage string, the mode-count guard (`:101`), and the header comment.
The existing `--comments` text mode is **unchanged** — other callers must not be disturbed.

### 2.5 Exit codes (the R2 contract — AC 6)

R3 records `- scripts/run_release_panel.sh: PASS|FAIL (exit <code>) at <UTC timestamp>`, so these are a
published interface. One table for both modes:

| Exit | Meaning | Modes |
|---|---|---|
| 0 | PASS | both |
| 1 | usage error / missing prerequisite / `author-unresolved` | both |
| 2 | `range-derivation-failed: shallow clone` | both |
| 3 | `range-derivation-failed: no tag reachable from HEAD` | both |
| 4 | `NO-CONTENT: zero files after exclusions` | both |
| 5 | operational failure (`panel-artifact-missing`, `post-failed`, `comments-unreadable`) | both |
| 6 | verdict composed and posted, `result = FAIL` | execute |
| 7 | `verdict-missing` — no block matched author + head SHA | verify |
| 8 | a verdict check failed — reason names which | verify |

The **last line of stdout** in both modes is machine-greppable and stable:
```
release-panel: <execute|verify> <PASS|FAIL|NO-CONTENT|REFUSED> reason=<slug> base=<sha12> head=<sha12> files_reviewed=<n>
```
`reason=none` on PASS. Nothing else may be printed after it.

---

## 3. `scripts/run_panel.sh` — the mode-dispatch refactor

**Rule for `coder`:** every mode-dispatched function below carries a comment naming **both** callers
(AD-1 risk (b)), in this form:

```
# Callers: PR mode (run_panel.sh <PR#>) and RELEASE mode (run_release_panel.sh -> --release-range).
# Changing either branch changes a gate. Do not collapse them.
```

### 3.0 Argument parsing and mutual exclusion

Add to the `while` loop at `:92-111`:
```
--release-range)  [[ $# -ge 2 ]] || die "--release-range needs <base_sha>..<head_sha>"
                  RELEASE_RANGE="$2"; shift 2 ;;
```
Initialise `RELEASE_RANGE=""` and `PANEL_MODE="pr"` beside `PR=""` at `:85`. After the loop (before `:113`):

- `[[ -n "$RELEASE_RANGE" && -n "$PR" ]]` → `die "--release-range and a PR number are mutually exclusive"`.
  A **usage error**, not a precedence rule (AD-1).
- `[[ -n "$RELEASE_RANGE" && -n "$_PANEL_SUBCMD" ]]` → `die "--record/--reset are PR-mode only"` (TD-VF-4:
  the ledger does not exist in release mode).
- `[[ -n "$RELEASE_RANGE" ]]` → `PANEL_MODE="release"`, and validate the shape:
  `[[ "$RELEASE_RANGE" =~ ^[0-9a-f]{40}\.\.[0-9a-f]{40}$ ]]` else
  `die "--release-range must be <40-hex>..<40-hex> (derive it with run_release_panel.sh, never by hand)"`.
  This is AD-1's mitigation (c) made mechanical: a hand-passed abbreviated or symbolic range is rejected.

### 3.1 Edge 1 — `panel_resolve_identity()` (replaces `:213-223` and `:249-250`)

Sets: `PR`, `HEAD_SHA`, `BASE_SHA`, `PR_TITLE`, `PANEL_LEDGER`, `RUN_LABEL`, `RUN_DIR`.

- **PR branch** — the existing bodies of `:214-220` and `:223` verbatim, plus `RUN_LABEL="pr${PR}"`,
  `BASE_SHA=""`.
- **Release branch** — `BASE_SHA="${RELEASE_RANGE%%..*}"`, `HEAD_SHA="${RELEASE_RANGE##*..}"`, `PR=""`,
  `PR_TITLE="release range ${BASE_SHA:0:8}..${HEAD_SHA:0:8}"`, `PANEL_LEDGER=""`,
  `RUN_LABEL="release/${HEAD_SHA}"`.
- **Shared tail** — `RUN_DIR="${PANEL_RUN_DIR:-.ai-local/panel/${RUN_LABEL}-$(date +%Y%m%d-%H%M%S)}"` then
  `mkdir -p "$RUN_DIR"`. The `PANEL_RUN_DIR` override is §2.2 step 3's seam; in PR mode it is unset and the
  behaviour is byte-identical to today's `:249`.

`:280-281`'s info lines become mode-dispatched (`PR #$PR — …` vs `release ${BASE_SHA:0:8}..${HEAD_SHA:0:8} — …`).

**Engine carve-out 1 (TD-VF-3):** `:448` becomes
`PANEL_ADVISORY_FILE=".claudetmp/panel/advisory-${RUN_LABEL//\//-}-$(date +%Y%m%dT%H%M%S).md"`.
In PR mode `RUN_LABEL` is `pr42`, so the filename is unchanged from today. No other line in `:387-714`
may be touched by this edge.

### 3.2 Edge 2 — `panel_fetch_diff()` (replaces `:251-253`)

Sets `DIFF_FILE`, `CHANGED_FILES`.

- **PR branch** — `:251-253` verbatim.
- **Release branch:**
  1. Resolve `$RELEASE_LOGIC` (`scripts/oversight/release_panel_logic.py`) with the same two-step idiom as
     `$PANEL_LOGIC` at `:287-288` (script-relative, then CWD-relative).
  2. `python3 "$RELEASE_LOGIC" derive-range --exclusions "$EXCL"` → JSON; read `.reviewed[]` into a bash array
     `REVIEWED`. Non-zero exit → `die "release mode: range derivation refused — run via run_release_panel.sh"`.
     (Defensive only; `run_release_panel.sh` already refused upstream. Release mode must never be reachable
     with a bad range even if invoked directly.)
  3. `[[ ${#REVIEWED[@]} -gt 0 ]] || die "release mode: zero reviewable files after exclusions"`.
  4. `git diff "$BASE_SHA" "$HEAD_SHA" -- "${REVIEWED[@]}" > "$DIFF_FILE"`.
  5. `CHANGED_FILES="$(printf '%s\n' "${REVIEWED[@]}")"`.
  6. `printf '%s\n' "${REVIEWED[@]}" > "$RUN_DIR/reviewed-files.txt"`.

The pathspec on the `git diff` is what makes exclusions real: an excluded file must never reach a reviewer's
prompt, not merely be absent from the count. Do **not** use `--pathspec-from-file` (git-version dependent for
`git diff`); the array expansion is portable and the list is bounded by the release's file count.

### 3.3 Edge 3 — `panel_risk_floor()` (replaces `:291-297`, adds the AD-6 clamp)

Sets `FLOOR`, and in release mode `VALIDATOR_TIER`.

- **PR branch** — `:291-297` verbatim (`triage-floor`, then the `AI-Risk:` trailer scan, then `max_risk`).
- **Release branch:**
  1. `FLOOR` from `triage-floor` over `CHANGED_FILES` — same call as `:291-292`. **No trailer scan** (`gh pr
     view --json commits` has no meaning over a range).
  2. Validator composite over the same range: run
     `bash scripts/oversight/run_validators.sh "${REVIEWED[@]}"` (explicit paths — run_validators' own
     autodetect, and hence TD-VF-1's degeneracy, is bypassed), then read `.tier` from
     `.claudetmp/oversight/validators/summary.json` — **only if that file's mtime is at or after the moment
     the invocation began.** A stale summary from an unrelated earlier run must be treated as absent.
  3. Unavailable / unparseable / validators non-zero → `VALIDATOR_TIER="unavailable"`, `warn` loudly, and
     record it in the verdict's `risk.validator_tier`. Do not abort: the deterministic floor and the MEDIUM
     clamp still apply, and the degradation is *visible in the posted comment* rather than silent.
     Otherwise `FLOOR="$(max_risk "$FLOOR" "$VALIDATOR_TIER")"`.
  4. **`FLOOR="$(max_risk "$FLOOR" MEDIUM)"`** — unconditional, the last statement of the release branch.

Step 4 is AD-6's clamp and must live **here**, at floor-computation time. It must **not** be a second guard
inside the `rank < 1` branch at `:365-372`: that branch is one refactor away from being lifted out, taking the
guard with it. With the clamp here, `:365-372` is unreachable in release mode by construction and needs no
edit at all. `coder` must leave `:365-372` untouched.

`:299-328` (override / Haiku / fallback) is unchanged and mode-invariant: every branch already clamps to
`$FLOOR` via `max_risk`, so a clamped floor propagates with no further edit.

### 3.4 Edge 3b — roster (`:374-385`) and SQC (`:330-362`)

- **SQC (`:335-362`)** — runs unchanged in both modes (it keys on `HEAD_SHA`, which release mode sets). Its
  output is **advisory only** in release mode (AD-6): the `SAMPLED` variable must not reach the roster.
- **Roster (`:374-385`)** — add a release branch *before* the existing `if [[ "$RISK" == "LOW" ]]`:
  ```
  release:  ROSTER=("agy:correctness" "codex:adversary")
            [[ "$(rank "$RISK")" -ge 2 ]] && ROSTER+=("codex:security")
            ROSTER+=("ipcheck:ip")
  ```
  `codex:adversary` is **unconditional** — never gated on `SAMPLED` (contrast `:381`). Result: MEDIUM →
  `agy:correctness, codex:adversary, ipcheck:ip`; HIGH/CRITICAL → `+ codex:security`. Sampling can only ever
  be a no-op on this set, which is the literal reading of "must not REDUCE roster" (REQ-A3 / AC 3).
  The LOW branch at `:375-376` is unreachable in release mode (§3.3 step 4) and is left as-is.

### 3.5 Engine carve-out 2 — chunk counters (`:481-493`, TD-VF-3)

Initialise `CHUNKS_ATTEMPTED=0` and `CHUNKS_COMPLETED=0` beside `RESPONSES_JSON="[]"` at `:472`. Inside the
per-chunk loop (`:481-493`):
- increment `CHUNKS_ATTEMPTED` immediately after `ci=$((ci+1))` (`:482`);
- increment `CHUNKS_COMPLETED` only on the **success** path of `call_model` — i.e. inside the `||` block's
  *absence*: after `:488`'s closing brace when the failure branch was not taken. Concretely, set a local flag
  in the failure branch (`:484-488`) and increment only when unset.

Effect: a required reviewer's failure already `die`s (`:485`), so it never reaches a verdict. The **ipcheck
degradation** at `:487` (`raw='{"findings":[]}'`) is the case these counters exist to catch — it leaves
`completed < attempted`, which AD-7 check 7 turns into a gate FAIL. That is deliberate: "a skipped chunk is a
FAIL" (REQ-A8 / AC 8), including a silently-degraded IP pass.

Counters increment in **both** modes; only release mode reads them. No control flow changes. These two
increments plus `:448` are the *complete* set of permitted engine edits.

### 3.6 Edge 4 — `panel_emit()` (the `:652-759` span) and the ledger (TD-VF-4)

Mode-dispatched, in `run_panel.sh` line order:

| Lines | PR mode | Release mode |
|---|---|---|
| `:223` ledger path | unchanged | `PANEL_LEDGER=""` (§3.1) |
| `:229-247` `--record`/`--reset` | unchanged | rejected at parse time (§3.0) |
| `:588-618` `NEW_BLOCKING_COUNT` | unchanged | skip the heredoc; `NEW_BLOCKING_COUNT="$TIER1_COUNT"` |
| `:628-650` `LEDGERED_FLAGS` | unchanged | `LEDGERED_FLAGS=()` — skip the block |
| `:655-659` `post_thread` | unchanged | never called |
| `:665-707` thread loop | unchanged | **skipped wholesale**; `POSTED=0`, `SUPPRESSED_COUNT=0`, `UNANCHORED=""` |
| `:713-714` `render-tier` | unchanged | **unchanged** — findings still render, Tier 1 first (AD-5) |
| `:720` header line | unchanged | add `Release candidate SHA:` + the reviewed range; drop "posted as threads" |
| `:726-731` tier sections | unchanged | **unchanged** |
| `:732-734` SQC prose | unchanged | replace with `> SQC sample: advisory only in release mode (roster unaffected).` when `RATE > 0` |
| `:735-737` `UNANCHORED` | unchanged | never non-empty (loop skipped) |
| `:738-742` CRITICAL blast-radius | unchanged | skip the `gh pr view` trailer scan; at CRITICAL append the note unconditionally, reworded for a range |
| `:743-745` IP caveat | unchanged | **unchanged** |
| `:746` footer | unchanged | footer without "threads must be resolved before merge" |
| `:748-759` posting | unchanged | **post nothing**; write `SUMMARY_BODY` to `$RUN_DIR/summary-body.md` |

The last row is the key seam: `run_panel.sh` has no issue number and AD-4 requires `post_comment.sh --app
worker`, so release mode is **GitHub-silent** and produces an on-disk artifact. All posting lives in
`run_release_panel.sh` (§2.2 step 6).

Skipping the thread loop is AD-5's whole point: with no PR diff to anchor to, `:700-705` would fail once per
finding and dump everything into `UNANCHORED` — 50 failed API calls producing a degraded summary.

**Ledger rationale, for the record:** suppression exists to stop a per-PR panel re-posting a thread the author
already triaged. Release mode posts no threads, so suppression has nothing to suppress — but the ledger, left
enabled with an empty `$PR`, would resolve to a *shared* `.ai-local/panel/pr-ledger.jsonl` and silently drop
tier-1 findings from `NEW_BLOCKING_COUNT`, directly contradicting AD-7 check 10. Disabled, not adapted.

### 3.7 Edge 5 — `panel_write_verdict()` (replaces `:762-784`)

- **PR branch** — `:762`, `:765-769`, `:771-784` verbatim (`panel-verdict.json`, `exit 3` on blocking).
- **Release branch** — write `$RUN_DIR/panel-release.json`:

```json
{
  "mode": "release",
  "base_sha": "<40hex>", "head_sha": "<40hex>",
  "effective_tier": "MEDIUM|HIGH|CRITICAL",
  "deterministic_floor": "…", "validator_tier": "…|unavailable",
  "roster": [{"reviewer":"agy","lens":"correctness","status":"ok"}],
  "findings": {"total":0,"tier1":0,"tier2":0,"tier1_undispositioned":0},
  "arbiter_salvaged": false,
  "chunks_attempted": 0, "chunks_completed": 0,
  "files_reviewed": ["…"],
  "run_dir": ".ai-local/panel/release/<head_sha>-<ts>",
  "summary_body_path": "<run_dir>/summary-body.md",
  "arbiter_sha256": "<hex>", "findings_raw_sha256": "<hex>",
  "sqc": {"sampled": false, "rate": 0, "advisory": true}
}
```
  `tier1_undispositioned` **equals** `tier1` in release mode (no ledger). `roster[].status` is `"ok"` for every
  reviewer that completed all its chunks, `"degraded"` otherwise (only reachable for `ipcheck`; the others
  `die`). The two `*_sha256` values hash `$RUN_DIR/arbiter.json` and `$RUN_DIR/findings.raw.json` — they let
  `--verify` check nothing (AD-4 says so plainly) but make a later on-machine audit decisive.
  Then **`exit 0`** when the engine completed. Release mode never exits 3: the PASS/FAIL judgement belongs to
  `compose_verdict` (§1.6), which is the single place the verdict contract lives (AD-9 row 1).

---

## 4. `scripts/oversight/release_panel_exclusions.txt`

Byte-for-byte the AD-3 block — the four generated artifacts, the two audit paths, `docs/releases/**`, with
AD-3's comments intact. **Add nothing. Remove nothing.** Specifically **not** excluded, and `coder` must not
add them: `docs/**`, `contract/**`, `.claude/agents/**`, `packs/**`, `audit/*.md`.

Add a header block, above AD-3's content, in the style of `scripts/framework/protected_surfaces.txt:1-14`:
purpose, the consumer (`scripts/oversight/release_panel_logic.py`), the glob syntax note, and the sentence
**"This file's sha256 is recorded in every release-panel verdict; editing it invalidates every prior verdict."**
The header is comments only, so it is inside `load_globs`' `#` handling — but it *does* change the file's
sha256, which is exactly the intended coupling.

---

## 5. Test checklist — `tests/oversight/test_release_panel_logic.py` (+ one shell smoke)

Enumerated so `unit-test` has a checklist, not a theme. Every case names the AC or AD clause it discharges.
Git is faked by monkeypatching `release_panel_logic.run_git` (§1.2); no test may require a real tag, a real
network, or a vendor CLI.

### 5.1 Range derivation — the four AD-2 states (AC 1)

| ID | Case | Expect |
|---|---|---|
| T-R1 | `is-shallow` → `true` | `state=="SHALLOW"`, reason names shallow clone, `remediation=="git fetch --unshallow --tags"`; `latest_tag` **never called** |
| T-R2 | not shallow, `git describe` exits non-zero | `state=="NO_TAG"` |
| T-R3 | not shallow, `git describe` exits 0 with empty stdout | `state=="NO_TAG"` (empty ≠ found) |
| T-R4 | tag found, `rev-parse <tag>^{commit}` fails | `state=="NO_TAG"`, reason `base sha unresolvable` — **not** a fifth state |
| T-R5 | tag found, diff lists only excluded paths | `state=="NO_CONTENT"`, `files_in_range>0`, `reviewed==()` |
| T-R6 | tag found, diff empty | `state=="NO_CONTENT"` |
| T-R7 | happy path, mixed included/excluded | `state=="OK"`, `reviewed` sorted, `files_in_range == len(reviewed)+len(excluded)` |
| T-R8 | **no `HEAD~1` anywhere** | assert `"HEAD~1"` appears in no `run_git` call across T-R1..T-R7 |
| T-R9 | `changed_files` uses two-dot | assert the recorded argv is `["diff","--name-only",base,head]`, never `f"{base}...{head}"` |
| T-R10 | shallow **and** no tag | `state=="SHALLOW"` — precedence, not `NO_TAG` |

### 5.2 Exclusions and digests (AD-3, AC 8)

| ID | Case | Expect |
|---|---|---|
| T-E1 | the shipped file parses | exactly AD-3's 7 globs, comments/blanks dropped |
| T-E2 | `audit/log/2026/09/x.json` | excluded |
| T-E3 | `audit/report.md` | **reviewed** — `audit/*.md` is not excluded |
| T-E4 | `docs/ADR-x.md`, `contract/OVERSIGHT-CONTRACT.md`, `.claude/agents/worker.md`, `packs/django/coder.md` | all **reviewed** (AD-3's "deliberately NOT excluded") |
| T-E5 | `scripts/framework/validation-stamps/a/b.json` | excluded (`**` crosses separators) |
| T-E6 | `SCRIPTS-INDEX.md`, `.github/CODEOWNERS`, `.hos-manifest`, `docs/releases/v0.6.0.md` | excluded |
| T-E7 | `exclusions_sha256` | equals `sha256` of the file bytes; changes when one comment character changes |
| T-E8 | `files_digest([])` | `e3b0c442…` (empty-string digest) |
| T-E9 | `files_digest` order-independence | `["b","a"]` and `["a","b"]` give the same digest |
| T-E10 | `files_digest` formula | equals `sha256(b"a\nb\n")` for `["a","b"]` — trailing newline on the last entry |
| T-E11 | missing exclusions file | raises; CLI exits 1 — **never** an empty glob list |
| T-E12 | no second glob engine | `apply_exclusions` delegates to `require_human_approval.glob_to_regex` (patch it, assert called) |

### 5.3 Verdict compose, extract, select, verify (AC 6, AC 7, AD-7)

Compose (AC 6):

| ID | Case | Expect |
|---|---|---|
| T-C1 | happy panel json | every AD-4 field present with AD-4's exact names; `schema_version==1`; `artifact=="hos-release-panel-verdict"`; `range.derivation=="since-tag"` |
| T-C2 | tier1_undispositioned = 2 | `result=="FAIL"`, `verdict_reason=="tier1-undispositioned"` |
| T-C3 | `arbiter_salvaged = true` | `result=="FAIL"`, reason `arbiter-salvaged` (AC 5 half) |
| T-C4 | `chunks_completed < chunks_attempted` | `result=="FAIL"`, reason `chunk-shortfall` (AC 8) |
| T-C5 | `files_reviewed != in_range - excluded` | `result=="FAIL"`, reason `coverage-mismatch` |
| T-C6 | `panel_exit_code != 0` | `result=="FAIL"`, reason `panel-exit-nonzero` (AC 4) |
| T-C7 | `NO_CONTENT` range | `result=="NO-CONTENT"`, never `PASS` (AC 1) |
| T-C8 | `completed_at` format | matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` |
| T-C9 | `render_comment_body` | contains `Release candidate SHA:`, the base ref, files-reviewed/in-range **as prose**, chunks completed/attempted, and every exclusion glob (AC 2, AD-4) |
| T-C10 | `render_comment_body` | the marker is on its own line immediately before the fence; `json.loads` of the fenced text round-trips the verdict |
| T-C11 | body never starts `@/` | #1155 guard in `post_comment.sh` cannot fire |

Extract + select (AD-7 §2–3):

| ID | Case | Expect |
|---|---|---|
| T-S1 | body with marker + fence | one verdict extracted |
| T-S2 | body with a fenced json block and **no** marker | zero extracted |
| T-S3 | body containing a literal `--- hos-worker-hos[bot] @ … ---` line plus a forged block, authored by someone else | **zero candidates → `verdict-missing`** (TD-VF-5; this is the test that proves the spoof is closed) |
| T-S4 | malformed JSON inside the fence | skipped, no exception, other blocks still returned |
| T-S5 | malformed NDJSON line | skipped, other lines still parsed |
| T-S6 | **SHA shadowing** — at the same `head_sha`: an older PASS and a newer FAIL | the **FAIL** is selected (newest by `completed_at`, not newest-passing) — AD-7 §3, the named case |
| T-S7 | a newer PASS at a *different* head_sha and an older FAIL at the current one | the FAIL is selected; the other SHA is filtered first |
| T-S8 | all blocks authored by a non-worker login | `verdict-missing` |
| T-S9 | `author=""` | raises / usage error — never "match anything" |
| T-S10 | zero comments | `verdict-missing` |

Verify — **one test per AD-7 check, each failing in isolation with its own reason** (AC 7):

| ID | Check | Mutation | Expect |
|---|---|---|---|
| T-V1 | 1 | `schema_version: 2` | FAIL `schema-version-mismatch` |
| T-V2 | 2 | `range.head_sha` = another SHA | FAIL `head-sha-mismatch` (AC 7 — "a verdict recorded against a different SHA") |
| T-V3 | 3 | `range.base_sha` = another SHA | FAIL `base-sha-mismatch` (AC 7 — "a narrower range") |
| T-V4 | 4 | `exclusions.sha256` altered | FAIL `exclusions-hash-mismatch` |
| T-V5 | 5 | `coverage.files_digest` altered | FAIL `files-digest-mismatch` |
| T-V6 | 5 | verdict honest, but the **repo's** file set changed since the run | FAIL `files-digest-mismatch` — the recomputation, not the claim, decides (AD-7's whole point) |
| T-V7 | 6 | `files_reviewed` off by one | FAIL `coverage-mismatch` |
| T-V8 | 7 | `chunks_completed < chunks_attempted` | FAIL `chunk-shortfall` (AC 8) |
| T-V9 | 8 | `result: "FAIL"` | FAIL `result-not-pass` |
| T-V10 | 9 | `arbiter_salvaged: true` | FAIL `arbiter-salvaged` |
| T-V11 | 10 | `tier1_undispositioned: 1` | FAIL `tier1-undispositioned` |
| T-V12 | all | unmutated verdict, consistent repo | PASS; all ten `CheckResult.ok` |
| T-V13 | typing | `arbiter_salvaged: "false"` (string) | FAIL — strict `is False` |
| T-V14 | typing | `tier1_undispositioned: "0"` (string) | FAIL — strict int |
| T-V15 | missing field | `coverage` key absent | FAIL on checks 5/6/7, **no exception** |
| T-V16 | refusal | `derive_range` returns SHALLOW at verify time | gate FAIL with the shallow reason — never PASS (AD-7 step 1) |
| T-V17 | completeness | all ten checks are reported even when the first fails | `len(checks) == 10` |
| T-V18 | forgery cost | `result` flipped to PASS on an otherwise-FAIL run | still FAIL — flipping the string is not enough |

### 5.4 Shell smoke tests

`tests/oversight/test_release_panel_shell.py` (pytest driving `bash`, matching this repo's existing
shell-test idiom), using a **fixture NDJSON comments file** and a temp git repo:

| ID | Case | Expect |
|---|---|---|
| T-S-1 | `--verify --issue 1` against a fixture whose verdict matches a temp repo | exit 0, last line `release-panel: verify PASS reason=none …` |
| T-S-2 | same, `head_sha` mutated | exit 8, `reason=head-sha-mismatch` |
| T-S-3 | fixture with no verdict block | exit 7, `reason=verdict-missing` |
| T-S-4 | **`--verify` invokes nothing** | with `agy`/`codex`/`claude`/`run_panel.sh` replaced by fail-on-call stubs on `PATH`, `--verify` still exits 0 (AD-7's hard prohibition) |
| T-S-5 | `--release-range X..Y 42` on `run_panel.sh` | non-zero, message names mutual exclusivity (AD-1) |
| T-S-6 | `--release-range HEAD~1..HEAD` | non-zero — abbreviated/symbolic ranges rejected (§3.0) |
| T-S-7 | `--release-range X..Y --record a b c` | non-zero — ledger subcommands are PR-mode only (TD-VF-4) |
| T-S-8 | `run_release_panel.sh --issue 5` in a shallow repo | exit **2**, stderr contains `git fetch --unshallow --tags` (AD-2 refusal 1; **this is the path that fires in this clone today**) |
| T-S-9 | `--verify --dry-run` | exit 1, usage error |
| T-S-10 | `--verify` with no resolvable author | exit 1, `author-unresolved` |
| T-S-11 | exit-code table | every code in §2.5 is reachable and documented in `--help` |

### 5.5 Not tested, and why

PR-mode behaviour of `run_panel.sh` cannot be regression-tested: the panel core has **never executed in this
repository** (E3/E4), so there is no baseline. AD-1 accepts this, and AD-9 requires a real out-of-band run
before PR 2 arms the gate. `unit-test` must not fabricate a PR-mode golden file that asserts today's untested
behaviour is correct — that would convert an unknown into a false guarantee.

---

## 6. `DECISIONS.md`, `SCRIPTS-INDEX.md`, `METHODOLOGY.md`

- **`DECISIONS.md`** — append at the bottom under a `## 2026-09-14` header (the file is append-only). Content
  is ADR §4's draft, prose tightened only. It **must** retain, as ADR §4 requires: the problem (E3/E4 — the
  release gate checked for step artifacts this repo never produced while the panel had never run at all); the
  retire-and-rehome decision with REQ-B split to #1622/#1623/#1624/#1625; the rejected per-PR backfill and why;
  the one-paragraph "what it does"; and the residual gaps — `overseer.md` untouched, #1621 open, AD-8's
  token-tracking gap, **AD-7's residual forgeability stated as a known limit**, and AF-1 **as corrected by
  TD-VF-1** (the shallow clone means the required `run_validators.sh` "diff since last tag" R2 row scores an
  empty range in this clone via the `origin/main` branch, not a one-commit range via the tag branch).
- **`SCRIPTS-INDEX.md`** — `bash scripts/framework/regen_all.sh`. Never hand-edited; `regen_all.sh --check`
  must pass in CI.
- **`METHODOLOGY.md`** — one line in the pipeline diagram, placing the release panel at the release-cut
  checkpoint (not in the inner loop, not in the per-PR outer loop), noting it is verified at R2 by
  recomputation and, in PR 1, armed by nothing.

---

## 7. What `coder` must not do

1. Do not add a second range derivation. §1.4 is the only one; both modes call it (AD-2).
2. Do not add a `HEAD~1` fallback, a `--force-range`, or any escape hatch around the three refusals. The panel
   refusing in this clone is the designed behaviour until ESC-1 is resolved (#1630).
3. Do not touch `scripts/run_panel.sh` between `:387` and `:714` except the two carve-outs in §3.1 and §3.5.
4. Do not rename or remove any AD-4 field. Additions are permitted; the listed names are frozen.
5. Do not put the AD-6 MEDIUM clamp inside the `rank < 1` branch (`:365-372`). §3.3 step 4 or nowhere.
6. Do not gate `codex:adversary` on `SAMPLED` in release mode (§3.4).
7. Do not use `gh api -f body=@path` (#1155) or hand-rolled `gh api` reads (#1175/#1192/#1204).
8. Do not touch `.claude/agents/worker.md`, `.claude/agents/overseer.md`, `token_tracker.py`, or
   `overseer.md`'s "Release-gate deep validation" section. All PR 2 or other issues.
9. Do not start until the three §8 items are answered.

---

## 8. Open items — escalated, not decided here

| # | Item | Route |
|---|---|---|
| TD-ESC-1 | **TD-VF-5 adds a 12th file** (`bootstrap/query_issues.sh --comments-json`) to AD-9's BINDING PR 1 table. Without it AD-7's author filter is spoofable by any commenter. Needs `architect` acknowledgement of the scope change. | `architect` |
| TD-ESC-2 | **TD-VF-3** — AD-1's "nothing between `:387` and `:714` changes" is false; two additive edits are unavoidable (`:448` advisory filename, `:481-493` chunk counters, the latter required *by* AD-7 check 7). Needs `architect` confirmation that these carve-outs are within AD-1. | `architect` |
| TD-ESC-3 | **TD-VF-4** — the SPEC-78 ledger is a sixth PR-bound edge AD-1 does not enumerate. §3.6 disables it in release mode, derived from AD-5 + AD-7. Needs `architect` confirmation, or a ruling that it is a release-scoped ledger instead. | `architect` |
| TD-VF-1 | AF-1's mechanism is misattributed (empty range via `origin/main`, not one commit via the tag branch). Affects **FU-3's framing and the DECISIONS entry**, not PR 1's code. Recorded, not papered over. | `architect` (FYI) |
| TD-VF-6 | "No subprocess CLI calls" read as "no vendor-CLI calls"; `git` confined to one seam. | `architect` (FYI) |

---

## Human Review Required

**RISK: MEDIUM-HIGH.** PR 1 is inert — nothing invokes it — so its live blast radius is the `run_panel.sh`
refactor alone, and PR mode has no working behaviour to regress (E3/E4). The risk is deferred, not absent:
this document fixes the contract a **release gate** will later enforce, and three of its clauses are the only
thing standing between "evidence of a review" and "an assertion that one happened" — §1.4's single derivation,
§1.5's normative `files_digest` formula, and §1.7's strict-typing rule. A digest formula that differs by one
newline between runner and verifier yields a gate that can never pass; a `verify` that coerces `"0"` to `0`
yields one that can be talked past.

**CONFIDENCE: HIGH** on §0 — every ADR anchor was re-derived from the working-tree blob this session, and the
two corrections (TD-VF-1, TD-VF-3) and two gaps (TD-VF-4, TD-VF-5) were each measured, not inferred. **HIGH**
on §1 and §5. **MEDIUM** on §3.3's validator-tier acquisition: `.claudetmp/oversight/validators/summary.json`
is a shared path and the mtime-freshness guard is the best available check short of a new flag on
`run_validators.sh`, which would exceed PR 1's scope. **MEDIUM** on §3.5's chunk-counter placement — it is the
only engine edit with a control-flow adjacency, and `coder` should expect a reviewer to look hard at it.

**BLAST RADIUS:** `scripts/run_panel.sh`, which ships to every consumer install (its PR mode is refactored
here, untested and untestable); `bootstrap/query_issues.sh`, a canonical entry point used by every autonomous
role (additive mode only, existing modes untouched); and, once PR 2 arms it, whether a MINOR/MAJOR release may
be cut. Nothing in PR 1 gates anything.

**Change classification: STRUCTURAL** — a new machine-readable artifact class with a verification contract, and
a control-flow refactor of a shipped script. ADR-1340 already carries the human's STRUCTURAL authorization for
PR 1 to proceed on `technical-design`'s completion (ADR §"Human Review Required", final paragraph). The three
**§8 escalations are new since that authorization** and are routed to `architect` before `coder` starts;
TD-ESC-1 in particular changes a BINDING file table and, if `architect` prefers, may warrant a human look.
