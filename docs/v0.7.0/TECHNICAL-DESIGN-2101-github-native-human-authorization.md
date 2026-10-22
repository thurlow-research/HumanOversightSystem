# TECHNICAL DESIGN — #2101 slice S1: the inert GitHub-native human-authorization verifier (`scripts/framework/human_authorization.py`)

**Status:** DRAFT, round 1. Awaiting architect review. Not yet handed to `coder`.
**Change class:** **additive** for this slice. S1 adds one new, inert, protected module with no caller, and makes two behaviour-preserving extractions in `requester_trust.py`. Nothing that runs today changes behaviour until S2 wires the consumers. The ADR the slice implements is STRUCTURAL and was human-approved (PR #2105, merged by `ScottThurlow`). The refinements this TD makes inside the ADR's delegation are listed in §10, each with its class.
**Date:** 2026-10-22
**Author:** technical-design (autonomous worker cycle; no human present)
**Issue:** #2101 · **Milestone:** v0.7.0 · **Slice:** S1 only (ADR-2101 §4). S2 (wiring, contract) and S3 (human-facing text) are out of scope. §9 records only what S1 must serve for them.
**Binding inputs (branch `worker-2101-s1-verifier-td-…` at `3cb0b7be5`):**
- `docs/v0.7.0/ADR-2101-github-native-human-authorization.md`: AD-1 to AD-4, AD-6, AD-9 and AD-10 are binding. AD-5, AD-7 and AD-8 are settled by the rulings below.
- `docs/v0.7.0/REQUIREMENTS-2101-github-native-human-authorization.md`: REQ-1 to REQ-13, with AM-1 to AM-8 applied.
- Human rulings from `ScottThurlow`'s own account, 2026-10-20T18:31:00Z: **ESC-1 A** (prescribed-form comment only), **ESC-3 yes** (the patch-id binding survives a clean merge from base), **ESC-4 yes** (`BF:<id>` items), **ESC-5 i** (retire the file, no derived record).

**Not open to any answer in this document:** REQ-2 / AD-3 (no bot ever authorizes, the human-proxy included), and REQ-9 (fail closed: no decision on incomplete data).

**Tree read at:** `3cb0b7be5`. Every `file:line` below was re-read in this session.

---

## 0. Reuse search (CLAUDE.md item 1)

I searched `scripts/` (recursively), `bootstrap/`, `bin/` and `scripts/automation/lib/*.py`.

| Need | Found | Decision |
|---|---|---|
| Bot denylist | `is_bot_reviewer(login, user_type, bot_accounts)` at `scripts/framework/require_human_approval.py:140-158`. It has three layers: `type == Bot`, the `[bot]` suffix, and `BOT_ACCOUNTS` membership. | **Reused** unchanged, imported. |
| Local bot set | `load_bot_accounts(repo_root)` at `requester_trust.py:301-322`. Its baseline is four keys of `machine-accounts.env`, unioned with env `BOT_ACCOUNTS`. A missing file gives an empty baseline. A present but unreadable file raises. | **Reused**. Its baseline loop is extracted as `bot_baseline_from_env_text` (§3). |
| Missing-file signal | `machine_accounts_file_absent(repo_root)` at `requester_trust.py:214-229` | **Reused** (REQ-9: an absent local file gives exit 3). |
| CODEOWNERS parser | `codeowners_humans(repo_root)` at `requester_trust.py:263-282`. It reads the **working tree**. | **Extracted** as `parse_codeowners_humans(text)`, which AD-3 names (§3). The working-tree function is never called by the verifier (AF-2). |
| `.env` line parser (never `source`d) | `_parse_env_file(path)` at `requester_trust.py:242-255` | **Extracted** as public `parse_env_text(text)` (§3). The default-branch `machine-accounts.env` arrives as text, not as a path. |
| Bounded `gh api` GET | `requester_trust._run_gh_get` at `:449-477`: one GET, no `--paginate`, no `-f`/`-F`, 30 s timeout, `OSError` and timeout mapped to failure. `fetch_collaborators` at `:480-533` is the page-loop model. | **Pattern copied, not imported.** The function is private, and AD-2 permits only `requester_trust`'s **public** functions. The verifier gets its own `_run_gh_get` with the same contract. |
| Pure predicate over pre-fetched data | `verify_codeowner_actor` at `requester_trust.py:614-645` | **Model** for `decide` (no I/O, no clock, no environment). |
| Own-comment unedited rule | `bootstrap/escalate_to_human.sh:221-228`, the jq clause `.updated_at == .created_at` at `:226` | **Rule reused** (AD-4). The live probe in §5 confirms its direction. |
| Comment page loop | `escalate_to_human.sh:218-243` (per_page=100, `COMMENT_PAGE_BOUND=30` at `:59`) | **Pattern reused.** The cap is set in §4.8. |
| Audit writer | The `audit_log` CLI `write [root]`, with event JSON on stdin and the relpath printed (`scripts/oversight/lib/audit_log.py:206-234`). The bash facade runs it as `cd <repo> && python3 -m scripts.oversight.lib.audit_log write <root>` (`scripts/oversight/lib/audit_log.sh:47`). | **Reused as a subprocess** (AF-3, AD-10). It is never imported. |
| Path canonicalization (SPEC-267) | `docs/v0.4.0/TECHNICAL-DESIGN-267-auth-enumeration.md` §3.1, and its prose port at `.claude/agents/oversight-evaluator.md:206-213` | **Ported verbatim** (§4.5). |
| C10 signal names | `scripts/oversight/change_classifier.py`: `ADDED_LINE_SIGNATURES` `:93-130`, `new-external-dependency` `:439`, `new-user-facing-surface` `:451` | **Not imported** (AM-2). The verifier checks only the kebab syntax of `C10:<signal>`. A test cross-checks the syntax against the classifier's names (§7, T-PR-12). |

**Found nothing** that parses a human-typed authorization form, computes a content binding, or reads a file at the server's default branch. Those parts are new.

---

## 1. Files in S1

| # | File | Kind |
|---|---|---|
| 1 | `scripts/framework/human_authorization.py` | new: verifier (form, `decide`, binding, fetcher, CLI, audit) |
| 2 | `scripts/framework/requester_trust.py` | edit: three behaviour-preserving extractions only (§3) |
| 3 | `tests/framework/test_human_authorization_predicate.py` | new |
| 4 | `tests/framework/test_human_authorization_parse_render.py` | new |
| 5 | `tests/framework/test_human_authorization_binding.py` | new |
| 6 | `tests/framework/test_human_authorization_fetch.py` | new: fault injection |
| 7 | `tests/framework/test_human_authorization_cli.py` | new: exit contract, JSON, audit, import graph |
| 8 | `tests/framework/test_requester_trust.py` | extend: pin the extractions, and update one conformance test that S1 would otherwise break (§3.4) |
| 9 | `scripts/framework/framework_consumer_files.txt` | edit: ship the verifier |
| 10 | `research/findings/api-field-shape-verification.md` | extend: the AD-4 probe record (§5.3) |
| 11 | `SCRIPTS-INDEX.md` | regenerate with `scripts/framework/regen_all.sh` |

That is **11 files**, matching the ADR's S1 row. All are inline-fixture tests, with no fixture files. Protected surface: `scripts/framework/**` (files 1, 2 and 9). The human gate applies. `security-reviewer` and `privacy-reviewer` are mandatory (ADR header). Not touched: `.claude/agents/**`, `contract/**`, `scripts/automation/**`, `scripts/oversight/**`, `bootstrap/**` and `bin/**`.

---

## 2. Organizing rules (checks the coder can verify)

1. **Purity boundary.** `parse_act`, `render_form`, `render_request`, `canonicalize_path`, `parse_item`, `decide` and `fingerprint` read no clock, no environment, no file and no network. `parse_codeowners_humans`, `parse_env_text` and `bot_baseline_from_env_text` in `requester_trust` are equally pure.
2. **Three I/O seams, and only three.** Each is a module attribute that tests monkeypatch:
   - `_run_gh_get(endpoint) -> Any`: all GitHub reads.
   - `_run_git(repo_root, args, *, stdin=None) -> bytes`: all git.
   - `_audit_write(event, audit_root) -> bool`: the audit subprocess.

   Nothing else in the module spawns a process or opens a socket.
3. **No decision on incomplete data.** `decide` runs only after every input is complete: the binding, the diff file list, both CODEOWNERS and bot sources, and every comment page from every source. Any failure before that point is exit 3, with `covered == []` and `refusals == []`.
4. **Nothing in a clone confers authority.** The verifier never reads `.github/CODEOWNERS` from disk, and never reads any `.claudetmp/**` auth file. The one local file it writes besides audit records is the `--audit-on-change` suppression record (§4.11). That record can only suppress an audit write. It is never read to compute a verdict.
5. **Import graph (AM-2).** The verifier imports only the standard library, `scripts.framework.require_human_approval` and `scripts.framework.requester_trust`. It contains no `scripts.automation` and no `scripts.oversight` import. `audit_log` is reached only as `python3 -m scripts.oversight.lib.audit_log` in a subprocess argv.
6. **Only exit 0 means authorized.** `covered[]` is non-empty only when the exit is 0 or 1 **and** the acceptance audit event was written (§4.10). On exit 2, 3 or 4, `covered` is `[]`.

---

## 3. `scripts/framework/requester_trust.py`: extractions (behaviour byte-identical)

### 3.1 `parse_codeowners_humans(text: str) -> set[str]` (new, public, pure)

The body is the loop at `:271-282`, moved verbatim. It runs over `text.splitlines()`: strip; skip blank lines and `#` lines; `split()`; for each owner after the pattern, `lstrip("@")`, skip it if it contains `/`, then add `.lower()`. `codeowners_humans(repo_root)` becomes:

```
path = _codeowners_path(repo_root)
if not path.is_file():
    return set()
return parse_codeowners_humans(path.read_text(encoding="utf-8"))
```

Its exceptions are unchanged: a present but unreadable file still raises.

### 3.2 `parse_env_text(text: str) -> dict[str, str]` (new, public, pure)

The body is `_parse_env_file`'s loop at `:244-254`, moved verbatim and operating on `text.splitlines()`. `_parse_env_file(path)` becomes `return parse_env_text(path.read_text(encoding="utf-8"))`.

### 3.3 `bot_baseline_from_env_text(text: str) -> set[str]` (new, public, pure)

This is the baseline loop of `load_bot_accounts` (`:311-320`) over `parse_env_text(text)`: the four keys `BOT_WORKER_USERNAME`, `BOT_OVERSEER_USERNAME`, `BOT_HUMAN_USERNAME` and `COPILOT_BOT_LOGIN`; non-empty values, stripped and lowercased. It does **not** read `BOT_ACCOUNTS` from the environment. `load_bot_accounts` becomes:

```
path = _machine_accounts_path(repo_root)
baseline = bot_baseline_from_env_text(path.read_text(encoding="utf-8")) if path.is_file() else set()
env_accounts = {b.lower() for b in os.environ.get("BOT_ACCOUNTS", "").split() if b}
return baseline | env_accounts
```

**Why §3.2 and §3.3 exist (ARCH-Q5).** AD-3 requires `bots = load_bot_accounts(local) ∪ baseline(default-branch machine-accounts.env)`. The default-branch file arrives as text from the contents API. Without these two extractions, the verifier would need either a second `.env` parser (a drift site) or a private import. Both are worse. The module docstring's "Permitted imports" text is unchanged.

### 3.4 Tests in `test_requester_trust.py` (file 8)

- **Pin.** Add `TestParseCodeownersHumans`, which runs every existing `TestCodeownersHumans` case (`:97-139`) through `parse_codeowners_humans(text)` and asserts the same sets. Add `TestBotBaselineFromEnvText` with the four keys and the `BOT_ACCOUNTS=` line, which is ignored. Assert that `load_bot_accounts` results for the existing `TestLoadBotAccounts` cases (`:189-236`) are unchanged.
- **Required update, or S1 breaks the suite.** `TestConformance.test_no_second_codeowners_parser_in_framework` (`:663-684`) asserts that the set of `scripts/framework/*.py` files containing the string `CODEOWNERS` is exactly `{requester_trust.py, select_work_candidates.py}`. The verifier must name `.github/CODEOWNERS` in its contents-API endpoint, so it trips this test.
  - The coder adds `scripts/framework/human_authorization.py` to the expected set.
  - The coder adds `assert "parse_codeowners_humans(" in ha_text`.
  - The coder adds `assert "codeowners_humans(repo_root" not in ha_text` and `assert "read_text" not in ha_text`. The verifier must never read CODEOWNERS from disk (AF-2).

  The docstring gains one sentence naming the verifier as a delegating reader.
- **Extend.** Add `scripts/framework/human_authorization.py` to the `surface` list of `test_no_production_use_of_not_is_bot_reviewer` (`:636-653`). `decide` must never read `not is_bot_reviewer(...)` alone as authorization.

---

## 4. `scripts/framework/human_authorization.py`

The module docstring's first line is the `SCRIPTS-INDEX.md` description: `human_authorization.py — the GitHub-native human-authorization verifier (S1 of #2101, ADR-2101).` The docstring restates rules 1 to 6 of §2.

### 4.1 Imports (exhaustive)

- Standard library: `argparse`, `base64`, `binascii`, `dataclasses`, `datetime`, `hashlib`, `json`, `os`, `re`, `subprocess`, `sys`, `time`, `urllib.parse`, `uuid`, `pathlib`, `typing`.
- `from scripts.framework.require_human_approval import is_bot_reviewer`
- `from scripts.framework.requester_trust import (bot_baseline_from_env_text, load_bot_accounts, machine_accounts_file_absent, parse_codeowners_humans)`

These `from scripts.framework.X import` lines are also what `test_selection_call_sites.py:317-332` reads to check that every framework import is shipped. Both modules are already in `framework_consumer_files.txt` (`:81`, `:97`).

### 4.2 Module constants

```
SCHEMA = "hos-human-authorization/v1"
SOURCE = "issue-comment"                         # AM-7: the only source in v1
PAGE_SIZE = 100
COMMENT_PAGE_BOUND = 10                          # per source (issue, PR): 1,000 comments. Not a flag.
GH_TIMEOUT_SECONDS = 30                          # per gh invocation (requester_trust.py:59)
FETCH_BUDGET_SECONDS = 120                       # whole fetch phase, checked before each gh call
GIT_TIMEOUT_SECONDS = 60                         # per git invocation
AUDIT_TIMEOUT_SECONDS = 30                       # per audit_log subprocess
CODEOWNERS_PATH = ".github/CODEOWNERS"
MACHINE_ACCOUNTS_PATH = "scripts/framework/machine-accounts.env"
WEB_ROOT = "https://github.com"                  # render-request URLs only
CONSUMERS = ("evaluator", "pr-readiness", "overseer")

REPO_RE    = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
NUM_RE     = re.compile(r"^[1-9][0-9]{0,9}$")
SHA_RE     = re.compile(r"^[0-9a-f]{40}$")
REF_RE     = re.compile(r"^[A-Za-z0-9._/@{}~^-]{1,255}$")   # and must not start with "-"
TS_RE      = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
KEBAB      = r"[a-z0-9]+(?:-[a-z0-9]+)*"
ITEM_RE    = re.compile(rf"^(?:C7|RA-FALLBACK|C10:{KEBAB}|BF:{KEBAB})$")   # and len(item) <= 80
BINDING_RE = re.compile(r"^patch:[0-9a-f]{40}$")
FENCE_OPEN_RE = re.compile(r"^```[A-Za-z0-9_-]*$")

REFUSAL_REASONS = frozenset({"bot-actor", "not-codeowner", "edited", "stale", "wrong-step",
    "no-overlap", "malformed", "malformed-latest", "declined", "superseded", "api-failure"})
PARSE_ERRORS = frozenset({"marker-line", "unknown-key", "duplicate-key", "missing-field",
    "bad-step", "bad-binding", "empty-covers", "bad-item", "duplicate-item", "duplicate-field",
    "second-marker", "unexpected-line", "bad-path", "decline-extra-line", "unterminated-fence",
    "text-after-fence"})
ERROR_CODES = frozenset({"api-error", "timeout", "budget-exhausted", "pagination-bound",
    "payload-shape", "default-branch-unreadable", "codeowners-unreadable", "codeowners-empty",
    "machine-accounts-unreadable", "bot-accounts-empty", "git-failure", "ambiguous-merge-base",
    "empty-diff", "unrepresentable-path", "unsupported-object-format"})
```

`superseded` is an addition to AD-10's closed set (ARCH-Q3).

### 4.3 Types (all `@dataclass(frozen=True)`, all sequences `tuple`)

```
Comment:   id: int; url: str; login: str; user_type: str; created_at: str;
           updated_at: str; body: str; issue_number: int
Act:       verb: Literal["authorize","decline"]; step: int; binding: str | None;
           items: tuple[str, ...]; reviewed_files: tuple[str, ...]
ParseError: code: str (∈ PARSE_ERRORS); line: int | None; key: str | None
           # key ∈ {"step","binding","covers","reviewed_files"} or None; never human text
Refusal:   comment_id: int; url: str; login: str; actor_type: str; issue_number: int;
           created_at: str; content_sha256: str; reason: str; detail: str | None
Governing: comment_id: int; url: str; login: str; actor_type: str; issue_number: int;
           created_at: str; content_sha256: str;
           decision: Literal["authorize","decline","malformed","edited"]
Accepted:  governing: Governing; act: Act; overlap: tuple[str, ...]
Verdict:   authorized: bool; covered: tuple[str, ...]; unmet: tuple[str, ...];
           governing: Governing | None; accepted: Accepted | None;
           refusals: tuple[Refusal, ...]
Binding:   binding: str; base_sha: str; head_sha: str; merge_base: str;
           diff_files: tuple[str, ...]          # sorted, canonical, representable
Fetched:   default_branch: str; codeowners_text: str; machine_env_text: str;
           comments: tuple[Comment, ...]
class VerifierError(Exception): code: str (∈ ERROR_CODES); detail: str  # fixed-template text only
```

`ParseError.detail_text()` renders exactly `"<code>"`, `"<code>:<key>"` or `"<code>@L<n>"`. These are the only strings from a comment that ever leave the module, and they contain no body text (§4.10, privacy).

### 4.4 The form: grammar, `parse_act`, `render_form`

**Canonical form** (what `render_form` emits, with no trailing newline):

```
/hos authorize step=<N> binding=patch:<40 lowercase hex>
covers: <item> <item> …
reviewed_files:
  - <path>
  - <path>
```

The decline form is exactly `/hos decline step=<N>`.

**`parse_act(body: str) -> Act | ParseError | None`.** `None` means "not a candidate". The function is pure and total. It never raises on any `str`.

1. **Normalize.** Split on `"\n"`. Remove one trailing `"\r"` from each line, because web-UI bodies use CRLF. Strip a leading U+FEFF from line 1. Line numbers below are 1-based over these lines. "Blank" means `line.strip(" \t") == ""`.
2. Let `i` be the first non-blank line. If there is none, return `None`.
3. **Optional enclosing fence.** If `lines[i].strip(" \t")` matches `FENCE_OPEN_RE`, set `fenced = True` and advance `i` to the next non-blank line. If there is none, return `None`.
4. **Candidacy.** Let `head = lines[i].strip(" \t")`. The comment is a candidate iff `head.casefold()` starts with `"/hos authorize"` or `"/hos decline"`. Otherwise return `None`.
   - Matching is case-insensitive here so that `/HOS Authorize …` is reported as malformed rather than silently ignored (ARCH-Q6).
   - Every rule below is case-sensitive.
5. **Form region.** The region is lines `i+1 … k-1`, where `k` is chosen as follows:
   - Unfenced: `k` is the first index `> i` whose line equals `"---"` after `rstrip(" \t")`, or EOF.
   - Fenced: `k` is the first index `> i` whose stripped line is exactly ` ``` `. If there is none, return `ParseError("unterminated-fence", line=i+1)`.
   - After a closing fence, every later line must be blank, or the first non-blank one must be exactly `---`. Otherwise return `ParseError("text-after-fence", line=…)`.
6. **Marker line.**
   - `toks = head.split()`. Require `toks[0] == "/hos"` and `toks[1] in ("authorize", "decline")`. Otherwise return `marker-line`.
   - Every later token must match `^([a-z_]+)=(\S*)$`. Otherwise return `marker-line`.
   - Allowed keys are `{step, binding}` for authorize and `{step}` for decline.
     - Any other key gives `unknown-key`, with `key=None` because the key is human text.
     - A repeated key gives `duplicate-key:<k>`.
     - An absent key gives `missing-field:step` or `missing-field:binding`.
   - `step` must match `NUM_RE`, else `bad-step`. `binding` must match `BINDING_RE`, else `bad-binding`. Hex is lowercase only.
7. **Region, decline.** Every region line must be blank. Otherwise return `decline-extra-line@L<n>`.
8. **Region, authorize.** Walk the lines with `state ∈ {none, list}`.
   - A blank line is skipped. It does not end a list, per TD-267 §3.3.
   - If the stripped line case-insensitively starts with `/hos ` (or equals `/hos`), return `second-marker@L<n>`.
   - If the stripped line starts with `covers:`:
     - a second occurrence gives `duplicate-field:covers`;
     - `items = rest.split()`, and an empty list gives `empty-covers@L<n>`;
     - any item that fails `ITEM_RE` or is longer than 80 characters gives `bad-item@L<n>`;
     - a repeated item gives `duplicate-item@L<n>`;
     - `state = none`.
   - If the stripped line is exactly `reviewed_files:`:
     - a second occurrence gives `duplicate-field:reviewed_files`;
     - otherwise `state = list`.
   - If `state == list` and the line matches `^[ \t]*-[ \t]+(.*)$`:
     - `p = canonicalize_path(group1)`, and an empty `p` gives `bad-path@L<n>`;
     - append `p`, de-duplicating while preserving first occurrence.
   - A line matching `^[ \t]*-[ \t]*$` in `state == list` gives `bad-path@L<n>`.
   - If the stripped line matches `^[A-Za-z_]+:`, return `unknown-key@L<n>`.
   - Anything else is `unexpected-line@L<n>`.
   - After the walk, a missing `covers:` gives `missing-field:covers`.
   - A missing `reviewed_files:` is **not** a parse error. It yields `reviewed_files=()`, which `decide` refuses as `no-overlap` (AD-8 / REQ-6 put "absent" under `no-overlap`).
9. Return `Act(verb, step, binding or None, tuple(items), tuple(paths))`.

The **first** error encountered, scanning top to bottom, is returned. Every `return ParseError` path above has its own test row (T-PR-3).

**`render_form(step, binding, items, diff_files) -> str`** (pure). It emits the canonical form exactly:
- one space between tokens;
- `covers:` followed by one space, then the items in the given order, separated by single spaces;
- each path on its own line as two spaces, `- `, then the path;
- paths in the given order.

It raises `ValueError` on any invalid item, binding or step, on an empty `items` or `diff_files`, or on a non-representable path (§4.5). **Round trip:** for every valid input, `parse_act(render_form(...)) == Act("authorize", step, binding, items, diff_files)`. The same holds with the form wrapped in ` ```text ` … ` ``` ` fences.

**`render_request(step, binding, items, diff_files, *, issue_url, pr_url=None, findings=(), parse_error=None) -> str`** (pure; AD-9). `findings` is a tuple of `(id, source, description)`. `parse_error` is `(comment_url, detail_text)` or `None`. Output, in this order:
1. `### Action needed`
2. `**Action:** post this comment from your own GitHub account, exactly as shown. Delete any reviewed_files line for a file you did not review, but keep at least one.`
3. A ` ```text ` fence containing `render_form(...)`, then a closing fence.
4. `To decline instead, post:` followed by a ` ```text ` fence containing `/hos decline step=<N>`.
5. Only if any `BF:` item is present: `Blocking findings this covers:`, then one line per finding: `- BF:<id> — <source>: <description>`.
   - `source` and `description` are each made single-line (newlines become spaces) and truncated to 200 characters.
   - Any of the forbidden strings `Authorization required:`, `Release candidate SHA:`, `hos-escalation`, `hos-recommendation` or `hos-proxy-decision` (ADR-1928 AD-9) is replaced by `[removed]`.
   - A `BF:` item with no finding renders `(no description supplied)`.
6. Only if `parse_error` is set: `Your latest /hos comment (<url>) could not be read (<detail_text>). Post a corrected comment; the newest one counts.`
7. `Do not edit this comment, or any later comment of yours on this issue or PR. If anything needs to change, post a new comment.` This is the human-facing statement of §4.6's edit rule.
8. `**Where:** <issue_url>`, followed by ` (or the PR: <pr_url>)` if a PR URL is given.
9. `**Who:** the human CODEOWNER, from your own GitHub account. The human-proxy session cannot do this.`
10. `**Done when:** the next evaluator run reports the items covered.`

The output never contains `.claudetmp/` or `-human-authorization.md`. A test pins that (T-PR-9).

### 4.5 Paths: `canonicalize_path`, representability, overlap

`canonicalize_path(raw: str) -> str` is TD-267 §3.1 verbatim:
1. Strip leading and trailing ASCII whitespace.
2. If `len ≥ 2` and the first and last characters are the same and are `"` or `'`, drop both.
3. Drop one leading `./`.

It never lowercases, resolves or collapses anything.

**Representable** (needed so that render, then parse, is lossless): a non-empty, valid str with no character `< 0x20` or `== 0x7f`, `p == p.strip()`, not wrapped in matching quotes, and not starting with `./`. For a representable `p`, `canonicalize_path(p) == p`. `compute_binding` raises `VerifierError("unrepresentable-path")` if any diff path fails this test, which is exit 3 (fail closed; residual R-S1-3).

**Overlap** = `set(act.reviewed_files) ∩ set(binding.diff_files)`. Both sides are already canonical. Comparison is exact and case-sensitive. An empty overlap means `no-overlap`. The overlap is recorded, sorted, in `Accepted.overlap` and in the acceptance event (SPEC-267 AC-8).

### 4.6 `decide(comments, codeowners, bots, step, binding, required_items, diff_files) -> Verdict` (pure; AD-2, AD-3, AD-4, AD-8)

The argument order is AD-2's (`acts` is named `comments`, because non-candidates are also input).

**Preconditions.** If any of these fails, raise `ValueError`. The CLI never calls `decide` in these states.
- `codeowners` is non-empty and holds lowercased strings.
- `bots` is non-empty.
- `required_items` is non-empty, de-duplicated, and every item matches `ITEM_RE`.
- `binding` matches `BINDING_RE`.

**Definitions.**
- `sha(c) = hashlib.sha256(c.body.encode("utf-8")).hexdigest()`. This is the body exactly as returned, with no normalization.
- `edited(c) = c.updated_at != c.created_at`. This is string comparison, after `TS_RE` validation in the fetcher (§5 explains why this rule stands alone).
- `verified(c) = c.login != "" and not is_bot_reviewer(c.login, c.user_type, bots) and c.login.lower() in codeowners`. AD-3 rules 1 to 3: identity comes from the payload only.

**Algorithm.**
```
ordered = sorted(comments, key=lambda c: (c.created_at, c.id))       # AD-4 / AM-1 total order
refusals, P = [], []                                                # P = participants
for c in ordered:
    parsed = parse_act(c.body)                                      # None | Act | ParseError
    cand = parsed is not None
    if not verified(c):
        if cand:                                                    # recorded and ignored
            reason = "bot-actor" if (c.login and is_bot_reviewer(c.login, c.user_type, bots)) \
                     else "not-codeowner"
            refusals.append(R(c, reason, None))
        continue                                                    # non-candidate: no event
    if edited(c):
        P.append((c, parsed, "edited"));      continue              # §4.6.1: ANY edited body
    if not cand:
        continue                                                    # unedited chatter: ignored
    if isinstance(parsed, ParseError):
        P.append((c, parsed, "malformed"));   continue
    if parsed.step != step:
        refusals.append(R(c, "wrong-step", None)); continue         # never governs, never blocks
    P.append((c, parsed, "act"))

if not P:
    return Verdict(False, (), required_items, None, None, sorted(refusals))

for (c, parsed, kind) in P[:-1]:                                    # non-governing participants
    if kind == "edited":
        if parsed is not None: refusals.append(R(c, "edited", None))   # non-candidate edits: no event
    elif kind == "malformed":   refusals.append(R(c, "malformed", parsed.detail_text()))
    else:                       refusals.append(R(c, "superseded", None))

c, parsed, kind = P[-1]                                             # the governing comment
if kind == "edited":
    refusals.append(R(c, "edited", None if parsed is not None else "non-candidate"))
    gov = G(c, "edited")
elif kind == "malformed":
    refusals.append(R(c, "malformed-latest", parsed.detail_text())); gov = G(c, "malformed")
elif parsed.verb == "decline":
    refusals.append(R(c, "declined", None)); gov = G(c, "decline")
elif parsed.binding != binding:
    refusals.append(R(c, "stale", None)); gov = G(c, "authorize")
elif not (overlap := set(parsed.reviewed_files) & set(diff_files)):
    refusals.append(R(c, "no-overlap", None)); gov = G(c, "authorize")
else:
    gov = G(c, "authorize")
    accepted = Accepted(gov, parsed, tuple(sorted(overlap)))
    covered = tuple(i for i in required_items if i in parsed.items)
    unmet   = tuple(i for i in required_items if i not in parsed.items)
    return Verdict(not unmet, covered, unmet, gov, accepted, sorted(refusals))
return Verdict(False, (), required_items, gov, None, sorted(refusals))
```

`sorted(refusals)` orders by `(created_at, comment_id)`. Every candidate comment yields **exactly one** of: one `Refusal`, or the `Accepted`. This is AD-10's "one event per candidate", and T-P-20 pins it. The only non-candidate that yields an event is a governing edited non-candidate (§4.6.1).

**Rules, stated as the coder will test them.**
- **No accumulation.** The latest participant governs. An older valid authorize never fills items the governing act leaves out, so `covered` comes from one act only. A stale or no-overlap governing authorize gives `covered = ()` even if an older act would have been current. `render_request` always lists every required item, so the human posts the complete set in one comment.
- **Decline.** A governing decline makes the step unmet whatever the earlier bindings were. An authorize posted later governs if it is current (REQ-8).
- **Wrong step** never participates, so a CODEOWNER's act for step 4 on a shared issue neither blocks nor authorizes step 5.
- **Actor refusals precede everything.** A bot's or non-CODEOWNER's comment is never a participant, edited or not.

#### 4.6.1 Edited comments by a verified CODEOWNER participate whatever their current body (fail-closed refinement; ARCH-Q2)

AF-4 says an App with `issues: write` can edit a human's comment. If edited comments were simply dropped, as an edited *candidate* would naively be, a bot could **resurrect** an older authorize in two ways:
- edit the human's newer `/hos decline` into any other text, so it is no longer a candidate;
- change its `step=`, so it becomes `wrong-step` and is skipped.

The older authorize would then govern. So an edited verified-CODEOWNER comment is a participant **whatever its current body parses to**. If it is the newest participant, the result is unmet with reason `edited`. The cost is an over-refusal: if the human edits **any** of their own comments on the issue or PR that is newer than their latest act, the act is voided until they post a fresh one. Line 7 of `render_request` tells them so. Edits to comments **older** than the governing act have no effect.

### 4.7 Binding: `compute_binding(repo_root, base, head) -> Binding` (AD-5, AM-4)

Local git only. Every git call goes through `_run_git`.

**`_run_git(repo_root, args, *, stdin=None) -> bytes`.**
- argv is `["git", "-C", str(repo_root), *GIT_PIN, *args]`.
- `env` is built from `os.environ`, minus **every key starting with `GIT_`**. This removes `GIT_DIR`, `GIT_WORK_TREE`, `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`/`KEY_n`/`VALUE_n`, `GIT_DIFF_OPTS`, `GIT_EXTERNAL_DIFF` and `GIT_ATTR_SOURCE`. Three keys are then added: `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1` and `GIT_ATTR_NOSYSTEM=1`.
- Use `capture_output=True`, `timeout=GIT_TIMEOUT_SECONDS` and `check=False`.
- A non-zero exit, `OSError` or `TimeoutExpired` raises `VerifierError("git-failure")`. The detail names the git subcommand only, never stderr.

```
GIT_PIN = ["-c", "core.quotePath=true", "-c", "core.attributesFile=/dev/null",
           "-c", "core.fsmonitor=false", "-c", "diff.algorithm=myers",
           "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false",
           "-c", "diff.suppressBlankEmpty=false", "-c", "diff.relative=false",
           "-c", "diff.indentHeuristic=true"]
```

**Steps.**
1. Validate `head` against `SHA_RE`, and `base` against `REF_RE`, also rejecting a leading `-` (CLI exit 2).
2. `base_sha = _run_git(["rev-parse", "--verify", "--quiet", "--end-of-options", base + "^{commit}"])`, then strip it. It must match `SHA_RE`; otherwise raise `git-failure`. A 64-hex result raises `unsupported-object-format`.
3. `_run_git(["cat-file", "-e", "--end-of-options", head + "^{commit}"])`. A missing commit, for example in a shallow clone, raises `git-failure`.
4. `mbs = _run_git(["merge-base", "--all", base_sha, head]).split()`. Zero entries raise `git-failure`. More than one raises `ambiguous-merge-base` (criss-cross history, fail closed). Otherwise `merge_base = mbs[0]`.
5. **Patch.**
   ```
   patch = _run_git(["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
                     "--full-index", "--binary", "--diff-algorithm=myers", "--unified=3",
                     "--inter-hunk-context=0", "--indent-heuristic", "--no-relative",
                     "--src-prefix=a/", "--dst-prefix=b/", "--ignore-submodules=none",
                     "--submodule=short", "-O/dev/null", merge_base, head, "--"])
   ```
   This is the ADR string's flags plus additional pins, never fewer. **`--text`/`-a` is forbidden** (see the evidence below).
6. If `patch == b""`, raise `empty-diff`. A step with no diff has nothing to authorize.
7. `out = _run_git(["patch-id", "--verbatim"], stdin=patch)`. `--verbatim` implies `--stable`, which is order-independent (`git patch-id` docs on git 2.53.0), so `patchid.*` config is overridden. Take the first whitespace-separated token. It must match `SHA_RE`; otherwise raise `git-failure`, or `unsupported-object-format` on 64 hex. `binding = "patch:" + token`.
8. **Diff files.** `_run_git(["diff", "--no-ext-diff", "--no-renames", "--name-only", "-z", "--no-relative", "--ignore-submodules=none", merge_base, head, "--"])`. Split on `b"\0"` and drop the final empty entry. Decode each entry as strict UTF-8; failure raises `unrepresentable-path`. Every path must be representable (§4.5). Sort and de-duplicate. With `--no-renames`, a rename lists both paths.

**Local experiment run for this TD** (scratch repo under `$TMPDIR`, git 2.53.0, the exact flag set above):

| Case | Result |
|---|---|
| Baseline | `f88e5f41…` |
| Hostile global `~/.gitconfig` (patience, `renames=copies`, `noprefix`, `context=10`, `mnemonicPrefix`, textconv driver, `patchid.stable=false`, `quotePath=false`), **plus** hostile repo-local config (histogram, copies, `context=0`, textconv driver, `core.attributesFile`), **plus** `.gitattributes` `*.py diff=evil` | `f88e5f41…` **(same)** |
| Clean merge of `main` into the step branch (`main` changed an unrelated file) | `f88e5f41…` **(same; ESC-3)** |
| Whitespace-only commit (a trailing space) | `064855f0…` **(changed; AF-6)** |
| Repo-local `.git/info/attributes` `* -diff` | `3be4a72c…` **(changed: over-refusal, closed; R-S1-2)** |
| Two different binary payloads at one path, `--binary` | different ids **(content bound)** |
| The same two payloads with `--text` | **identical ids**: `--text` makes `patch-id` blind to binary content. This is why `--text` is forbidden. |
| `core.compression` 0 or 9 with `--binary` | same id. `patch-id` hashes the full-index blob ids of a binary diff, not the deflate stream, so **`--full-index` is load-bearing**. |

`.git/info/attributes` cannot be neutralized from the command line. Its only effect is to make one clone compute a *different* id (`stale`, closed), never to make two different contents collide. Tests T-B-5 and T-B-6 pin both directions.

### 4.8 Fetcher: `fetch(repo, issue, pr) -> Fetched` (AD-3, REQ-9)

**`_run_gh_get(endpoint) -> Any`** has the contract of `requester_trust._run_gh_get` (`:449-477`), re-implemented:
- argv `["gh", "api", endpoint]`;
- no `--paginate`, no `-f`/`-F`/`--method`/`--input`;
- `timeout=GH_TIMEOUT_SECONDS`.

On 404, `gh` prints the error JSON to stdout **and exits 1** (probed: `contents/.github/NOPE` gives `rc=1`). So the return code is checked **before** any parse, and non-zero is a failure.

Failures map as follows:
- `TimeoutExpired` gives `timeout`.
- `OSError` gives `api-error`.
- A non-zero exit gives `api-error`. A rate limit is the same code. The stderr text goes only to the module's own stderr diagnostic line, never into JSON or audit.
- Invalid JSON gives `payload-shape`.

A module-level deadline `time.monotonic() + FETCH_BUDGET_SECONDS` is checked before every call. If it has passed, raise `budget-exhausted`.

**Reads, in this order** (`o/r` is `--repo`):
1. `repos/{o}/{r}` gives a dict with a non-empty str `default_branch`. Anything else is `default-branch-unreadable`.
2. `repos/{o}/{r}/contents/.github/CODEOWNERS?ref={quote(default_branch, safe='')}` must give a dict with `type == "file"`, `encoding == "base64"` and a str `content`. The content is decoded with `base64.b64decode(content, validate=False)` after removing `"\n"`, then decoded as strict UTF-8. Any failure, including an `api-error` from a 404, is **`codeowners-unreadable`** (the error code is re-mapped).
3. `repos/{o}/{r}/contents/scripts/framework/machine-accounts.env?ref=…` gets the same handling, but failures are **`machine-accounts-unreadable`**. **Consumer prerequisite (note for S2/pm):** a consumer project must commit `scripts/framework/machine-accounts.env` on its default branch, or every `verify` exits 3. That is fail-closed and per REQ-9. Today's consumer installer does not ship that file (`framework_consumer_files.txt` has no entry for it).
4. `repos/{o}/{r}/issues/{issue}/comments?per_page=100&page={k}` for `k = 1 … COMMENT_PAGE_BOUND`. The endpoint string carries the query literally, as in `requester_trust.py:519`.
   - Each page must be a list; otherwise `payload-shape`.
   - A page with fewer than 100 items ends the loop.
   - If page `COMMENT_PAGE_BOUND` is full, raise **`pagination-bound`**.
   - No partial list is ever returned.
5. If `--pr` is given, step 4 is repeated for `--pr`. PR conversation comments are `/issues/{pr}/comments` (AD-1: one read path).

**Comment normalization** (`_comment_from(obj, issue_number) -> Comment`): any violation raises `payload-shape`, so the decision never sees a half-understood record.
- `obj` is a dict.
- `id` is an `int > 0` and not a `bool`.
- `html_url` is a str.
- `body` is a str.
- `created_at` and `updated_at` are strs matching `TS_RE`.
- `user` is a dict, or `None`, which gives `login = ""` and `user_type = ""`. `user.login` and `user.type` are strs when present.

A comment id appearing twice across both sources also gives `payload-shape`.

**Cost.** At most `3 + 2 × 10 = 23` GETs per `verify`. The worst case on this repo today is 1 page per source (the busiest issue, #2139, has 45 comments across the 2,440 read in §5).

### 4.9 CLI

Invocation: `cd <repo> && python3 -m scripts.framework.human_authorization <subcommand> …`, which is the `bin/hos-cron:1278` pattern. `main(argv: list[str] | None = None) -> int`, then `sys.exit(main())`.

**Common options:** `--repo-root PATH` (default `.`; must be a git work tree, checked by the first `_run_git`).

**`verify`**
```
verify --repo <owner/repo> --step N --issue N [--pr N] --base <ref> --head <40-hex>
       --require <item>[,<item>…] (repeatable) --consumer evaluator|pr-readiness|overseer
       [--audit-on-change] [--audit-root PATH] [--json] [--repo-root PATH]
```

Usage validation gives exit 2, with one stderr line `human_authorization: usage: <fixed text>` and **no stdout and no audit**. Each of these is a usage error:
- `REPO_RE`, `NUM_RE`, `SHA_RE` or `REF_RE` fails;
- `--pr == --issue`;
- any `--require` item fails `ITEM_RE`;
- the de-duplicated `--require` list is empty;
- `--consumer` is not in `CONSUMERS`;
- `--audit-on-change` is given without `--consumer overseer`.

`--audit-root` defaults to `--repo-root`.

**Flow** (the first failure wins; every exit-3 path is one `VerifierError`):
1. `verification_id = uuid.uuid4().hex`. `verified_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`. These are the only clock and randomness reads.
2. `b = compute_binding(repo_root, base, head)`. Git runs first, so a git failure costs no network.
3. `f = fetch(repo, issue, pr)`.
4. **Bot set.**
   - If `machine_accounts_file_absent(repo_root)`, raise `machine-accounts-unreadable`.
   - `local = load_bot_accounts(repo_root)`, with `OSError` or `UnicodeDecodeError` raising `machine-accounts-unreadable`.
   - `bots = local ∪ bot_baseline_from_env_text(f.machine_env_text)`.
   - An empty set raises `bot-accounts-empty`.
5. `codeowners = parse_codeowners_humans(f.codeowners_text)`. An empty set raises `codeowners-empty`.
6. `v = decide(f.comments, frozenset(codeowners), frozenset(bots), step, b.binding, required, b.diff_files)`.
7. Audit (§4.10), with suppression under `--audit-on-change` (§4.11).
8. **Exit.**
   - 0 if `v.authorized` and the acceptance event was written (or suppressed).
   - 4 if `v.accepted` is set and its acceptance write failed. `covered` is then forced to `[]` and `unmet` to `required`.
   - 1 otherwise.
   - On a `VerifierError`: emit the single `api-failure` event, then exit 3.

**Exit contract (fixed; AD-2).** Exit 2 is a usage error. Every consumer treats any non-zero exit as "not authorized" for every item not in `covered`.

| Exit | `verdict` | Meaning |
|---|---|---|
| 0 | `authorized` | Every required item is covered by the governing act, and the acceptance event is recorded |
| 1 | `not-authorized` | Decided on complete data: no act, declined, stale, edited, malformed-latest, no-overlap, or some items uncovered |
| 2 | (no JSON) | Usage error |
| 3 | `undetermined` | Could not decide (`error.code ∈ ERROR_CODES`) |
| 4 | `audit-failed` | The governing act was valid, but its acceptance event could not be written, so nothing is covered |

**`--json` stdout:** exactly one line, `json.dumps(obj, sort_keys=True, separators=(",", ":"))`. Without `--json`, stdout is one summary line: `human_authorization: verdict=<v> step=<n> binding=<b|none> covered=<csv|-> unmet=<csv|-> refusals=<n> error=<code|none>`.

```
{
  "schema": "hos-human-authorization/v1",
  "verdict": "authorized" | "not-authorized" | "undetermined" | "audit-failed",
  "exit_code": 0 | 1 | 3 | 4,
  "verification_id": "<32 hex>", "verified_at": "<TS>",
  "consumer": "...", "repo": "o/r", "step": N, "issue": N, "pr": N | null,
  "base": "<ref as given>", "base_sha": "<sha>|null", "head": "<sha>", "merge_base": "<sha>|null",
  "binding": "patch:<hex>" | null,
  "required": [...], "covered": [...], "unmet": [...],
  "act": {"id", "url", "login", "type", "created_at", "content_sha256",
          "decision": "authorize"|"decline"|"malformed"|"edited", "issue_number"} | null,
  "overlap": [...],                      // SPEC-267 AC-8; [] unless an act was accepted
  "refusals": [{"id", "url", "login", "actor_type", "issue_number", "reason", "detail"}],
  "error": {"code": "<ERROR_CODES>", "detail": "<fixed template>"} | null,
  "audit": {"written": n, "failed": n, "suppressed": true|false}
}
```

This extends AD-2's field list compatibly. Every key is always present. On exit 3: `act = null`, `refusals = []`, `covered = []`, `unmet = required`, `overlap = []`, and `binding` is set only if step 2 succeeded.

**`binding`**: `binding --base <ref> --head <40-hex> [--repo-root PATH] [--json]`. It prints `patch:<hex>`, or with `--json` it prints `{binding, base_sha, head, merge_base, diff_files}`. Exits are 0, 2 or 3. It writes no audit.

**`render-request`** (AD-9; S3 is the caller):
```
render-request --repo o/r --step N --issue N [--pr N] --base <ref> --head <40-hex>
       --require <items> [--findings-file PATH] [--verdict-file PATH] [--repo-root PATH]
```
- It computes the binding and file list locally (exit 3 on git failure) and prints `render_request(...)`. Exits are 0, 2 or 3.
- The URLs are `WEB_ROOT/{repo}/issues/{issue}` and `WEB_ROOT/{repo}/pull/{pr}`.
- `--findings-file` is a JSON list of `{"id","source","description"}` strings.
- `--verdict-file` is a prior `verify --json` output. If its `refusals` contains `reason == "malformed-latest"`, that entry's `url` and `detail` become `parse_error`.
- An unreadable or ill-typed file is exit 2.
- It performs no network I/O and writes no audit. It never posts (AD-9: the worker posts it through `escalate_to_human.sh`).

### 4.10 Audit (AD-10, REQ-10)

**Writer seam.** `_audit_write(event: dict, audit_root: Path) -> bool` runs:
```
subprocess.run([sys.executable, "-m", "scripts.oversight.lib.audit_log", "write", str(audit_root)],
               input=json.dumps(event), text=True, capture_output=True,
               cwd=str(HOS_ROOT), timeout=AUDIT_TIMEOUT_SECONDS, check=False)
```
- `HOS_ROOT = Path(__file__).resolve().parents[2]` is the tree that contains `scripts/oversight/lib/audit_log.py`. `scripts/oversight/` has no `__init__.py`, and `-m` resolves it as a namespace package from `cwd`, as `audit_log.sh:47` does.
- It returns `True` iff the return code is 0 and the stripped stdout is non-empty (the relpath).
- `OSError` or a timeout returns `False`.
- The verdict is computed **before** any write (AF-3). A broken writer can corrupt the record, never the verdict.

**Common fields** (every event): `event`, `timestamp` (= `verified_at`), `verified_at`, `verification_id`, `consumer`, `repo`, `step`, `issue`, `pr`, `source` (`"issue-comment"`), `binding`, `head_sha`, `base_sha`, `merge_base`.

**`human-authorization`** is the existing §6a event (`contract/OVERSIGHT-CONTRACT.md:424`), extended compatibly. It is written once, for `Verdict.accepted` (the governing act was a valid, current, overlapping authorize), even if some required items stay unmet:
- `artifact` is the comment URL;
- `authorized_by` is the login;
- `content_sha256`;
- `decision` is `"authorize"`;
- `step`, which is unchanged in name.

Added fields: `comment_id`, `url`, `comment_issue`, `actor_type`, `covered`, `unmet`, `reviewed_files` (the act's list, as parsed), `overlap`.

**`human-authorization-refused`** (new). One event per `Refusal`:
- the common fields;
- `comment_id`, `url`, `comment_issue`, `login`, `actor_type`, `content_sha256`;
- `reason` (∈ `REFUSAL_REASONS`);
- `detail` (`ParseError.detail_text()`, `"non-candidate"`, or `null`).

**`api-failure` form.** One event on every exit 3. It carries the common fields plus `reason: "api-failure"` and `detail: <error code>`. It has **no** comment fields (AD-10). The reason keeps AD-10's name even when the cause is git or CODEOWNERS. `detail` carries the precise code.

**Order.** Refusal events and the acceptance event are written in `(created_at, comment_id)` order.

**Failure handling.**
- A failed acceptance write gives exit 4 (§4.9).
- A failed refusal or api-failure write leaves the exit unchanged. It adds one stderr line, `human_authorization: WARN audit-write-failed event=<event> comment_id=<id|none>`, and increments `audit.failed`.

**Privacy (for `privacy-reviewer`).** Events carry public logins, public comment URLs and ids, a sha256 of the body, repo-relative paths, and closed-vocabulary reason and detail codes. **No comment body or body fragment is ever logged or printed.** Parse-error details are codes and line numbers only. `unknown-key` deliberately omits the key text.

### 4.11 `--audit-on-change` (overseer only; AD-6)

AD-6 makes this an overseer flag. S2's file list does not include the verifier, so **S1 implements it** (pm-agent point 1, §9).
- **Record:** `<repo_root>/.claudetmp/human-authorization/audit-on-change.json`, of the form `{"v": 1, "entries": {"<repo>#<step>#<binding|none>": "<fingerprint>"}}`. `.claudetmp/` is persistent, uncommitted working state (CLAUDE.md "Temp and working-state locations" rule 2).
- **`fingerprint(...)`** (pure) is the sha256 of the canonical JSON of `{exit_code_before_audit, covered, unmet, act_id, act_decision, refusals: [[id, reason, detail]…], error_code}`.
- **Behaviour.**
  - If the record is readable and the entry equals the fingerprint, **write nothing**. Set `audit.suppressed = true`. The exit code is the pre-audit one, and an authorized verdict stays 0, because this clone already recorded that exact acceptance.
  - Otherwise, write the events normally. Update the entry (temp file plus `os.replace`) **only if every write succeeded**.
  - An unreadable or corrupt record is treated as absent, so the writes happen. A failed update is a stderr WARN only.
- **The record can only suppress a write.** It is never an input to `decide` or to the exit code (§2 rule 4). T-CLI-14 shows that a forged record cannot change the verdict.

---

## 5. AD-4 live probe (S1 obligation): which field signals a body edit

### 5.1 Method (read-only; nothing was created, edited or reacted to)

1. **All comments in this repo.** `GET repos/thurlow-research/HumanOversightSystem/issues/comments?per_page=100&sort=created&direction=asc&page=1…25` returned 2,440 comments, from 2026-06-12 to 2026-10-22. For each I recorded `id`, `user.login`, `user.type`, `created_at`, `updated_at`, `reactions.total_count` and `html_url`.
2. For every comment with `updated_at != created_at`: `GET …/issues/comments/{id}` for its `node_id`, then a GraphQL **query** (no mutation) for `createdAt`, `updatedAt`, `lastEditedAt`, `includesCreatedEdit`, `reactions.totalCount` and `userContentEdits(first:5){editedAt editor{login}}`.
3. **Reactions.** This repo has no reacted comments, so the same method was applied to public repos. I took pages 2 to 11 of `GET repos/{cli/cli, microsoft/vscode}/issues/comments?sort=created&direction=desc` and kept every comment with `reactions.total_count > 0`. For each reacted comment whose timestamps differed, I ran the GraphQL query above, plus `isMinimized`, `minimizedReason` and the `createdAt` of each reaction.
4. Contents-API shape: `GET repos/…/contents/.github/CODEOWNERS?ref=main` gives `{type:"file", encoding:"base64", content, sha, size}`. A missing path gives HTTP 404 with the JSON on stdout and `gh` rc=1.

### 5.2 Results

| Population | n | `updated_at == created_at` | `updated_at != created_at` | Cause of every `!=` |
|---|---|---|---|---|
| HOS repo, all comments | 2,440 | 2,426 | 14 | **14/14 real body edits.** GraphQL `lastEditedAt == updated_at` and `userContentEdits` ≥ 2 in every case. Editors: `ScottThurlow` ×8, `hos-worker-hos` ×4, `hos-overseer-hos` ×2. Each App edited only its own comments. |
| Public, reacted comments | 151 | **129** | 22 | 16 real body edits (`lastEditedAt == updated_at`). **5 hidden (minimized)**: `isMinimized=true` (spam ×4, low-quality ×1), `lastEditedAt=null`, no edits. 1 unexplained (`cli/cli` 5693523114: last edit 09-16T07:14:44Z, `updated_at` 09-17T09:13:48Z, not minimized now, no reaction at that instant). |

**Reaction timing.** In several comments reactions were added **after** `updated_at` and did not move it:
- `vscode` 6308694016: reaction at 05:21:32, `updated_at` 05:21:24;
- `cli/cli` 5921072446: reactions on 10-05, `updated_at` 10-01;
- `cli/cli` 5693523114: reactions on 09-18 and 09-19, `updated_at` 09-17.

### 5.3 Conclusion and design consequence

- **Reactions do not bump REST `updated_at`.** Evidence: 129/151, plus timestamped reactions later than `updated_at`.
- **Every observed body edit bumps it,** and equals GraphQL `lastEditedAt`: 30/30.
- **Hiding (minimizing) a comment bumps `updated_at` without an edit**, and one unexplained non-edit bump exists.

**Decision.** The REST rule `updated_at == created_at` is the **sole** pass condition. **The GraphQL `lastEditedAt` alternative pass condition that AD-4 permits is not adopted.** It would accept a *hidden* comment (`lastEditedAt` null), which is not the direction we want for a forgery control. It would also add a POST-transport GraphQL fetch to the trust path for no observed benefit.
- Any non-edit bump, such as a hide or the unexplained case, is an **over-refusal**: the human posts a new comment.
- This is AD-4's stated fail-closed direction, now backed by evidence.

**Residual R-S1-1 (stated).** REST timestamps have one-second resolution. An edit landing in the same wall-clock second as creation would leave `updated_at == created_at`. Exploiting it needs a bot to observe and rewrite a human's comment within one second of posting. I judge it negligible and do not mitigate it in v1. The architect may rule otherwise (ARCH-Q7).

**`research/findings/api-field-shape-verification.md` (file 10): content the coder appends.** Add a section `## 2026-10-22 probe: comment edit signal (#2101, ADR-2101 AD-4)` containing:
1. The method in §5.1. Name the endpoints and state "read-only: no comment was created, edited, hidden or reacted to".
2. The §5.2 table, verbatim, including the three timing examples.
3. The conclusion in §5.3, plus the design decision and residual R-S1-1.
4. The contents-API shape and the 404 rc=1 behaviour from §5.1 item 4.
5. One **Implications** bullet: "`updated_at` is an *any-change* signal, not an *edit* signal. Using it as an edit detector is safe only in the fail-closed direction, and any consumer that treats `updated_at != created_at` as proof of a body edit (rather than as 'refuse') is wrong for hidden comments."

---

## 6. Failure modes (S1 behaviour; extends ADR §3)

| Failure | Behaviour | Direction |
|---|---|---|
| `gh` non-zero, OSError, rate limit | exit 3 `api-error`, one api-failure event | Closed |
| One `gh` call exceeds 30 s | exit 3 `timeout` | Closed |
| Fetch phase exceeds 120 s | exit 3 `budget-exhausted` | Closed |
| Page 10 of a source is full | exit 3 `pagination-bound` | Closed |
| Payload not list/dict, bad field type, bad timestamp, duplicate id | exit 3 `payload-shape` | Closed |
| Repo metadata unreadable | exit 3 `default-branch-unreadable` | Closed |
| Default-branch CODEOWNERS 404/undecodable / no individual humans | exit 3 `codeowners-unreadable` / `codeowners-empty` | Closed |
| Local `machine-accounts.env` absent or unreadable; default-branch copy 404 or undecodable | exit 3 `machine-accounts-unreadable` | Closed |
| Bot set empty after the union | exit 3 `bot-accounts-empty` | Closed |
| Base or head missing, shallow clone, git error | exit 3 `git-failure` | Closed |
| Criss-cross merge bases | exit 3 `ambiguous-merge-base` | Closed (over-refusal) |
| Empty step diff | exit 3 `empty-diff` | Closed |
| Diff path with a control character, non-UTF-8, edge whitespace or wrapping quotes | exit 3 `unrepresentable-path` | Closed (R-S1-3) |
| SHA-256 object-format repo | exit 3 `unsupported-object-format` | Closed (R-S1-4) |
| Hostile global/local git config, `.gitattributes` textconv, `GIT_*` env | Neutralized; same id | — |
| Local `.git/info/attributes` `-diff` | Different id, so `stale` | Closed (R-S1-2) |
| Bot edits or deletes a human's *authorize* | `edited` / absent, so unmet | Closed |
| Bot edits a human's newer *decline* into chatter or another step | Still a participant (§4.6.1), so `edited` | Closed |
| Bot **deletes** a human's newer decline | The older current authorize governs | **Open: R-S1-5 / ARCH-Q1** |
| Comment hidden (minimized) | `edited` | Closed (over-refusal) |
| Acceptance audit write fails | exit 4, `covered = []` | Closed |
| Refusal audit write fails | Exit unchanged, WARN | Closed |
| Forged or corrupt `--audit-on-change` record | Writes happen, or are suppressed; the verdict is unchanged | Record-only |

**Residuals (stated).**
- **R-S1-1:** a same-second edit (§5.3).
- **R-S1-2:** a local `info/attributes` `-diff` gives an over-refusal.
- **R-S1-3:** an unrepresentable diff path blocks the step until it is renamed.
- **R-S1-4:** SHA-256 repositories are unsupported (they fail closed).
- **R-S1-5:** a decline deleted by a bot resurrects an older current authorize (ARCH-Q1).
- ADR R-1 to R-5 still stand.

---

## 7. Test plan (all deterministic, with no network; `gh` and the audit writer are recording fakes on the §2 seams; git runs for real in pytest `tmp_path` repos)

Shared helper (per file, no fixture files): `_c(id, login, type="User", created="2026-10-20T10:00:00Z", updated=None, body="", issue=2101)` builds a `Comment`. `_form(...)` calls `render_form`. Constants: `CO = frozenset({"scottthurlow"})`; `BOTS = frozenset({"hos-worker-hos[bot]", "hos-overseer-hos[bot]", "scottthurlow-claude[bot]", "copilot[bot]", "pat-machine-user"})`; `B = "patch:" + "a"*40`; `FILES = ("scripts/x.py", "docs/y.md")`.

### 7.1 `test_human_authorization_predicate.py` (`decide`)

| Id | Case | Expect |
|---|---|---|
| T-P-1 | REQ-2: `ScottThurlow`, `type=User`, a valid current act covering `C7` | authorized, covered `("C7",)` |
| T-P-2 | REQ-2: the same body by `scottthurlow-claude[bot]` (`type=Bot`) | `bot-actor`, unmet |
| T-P-3 | REQ-2: by `hos-worker-hos[bot]` | `bot-actor` |
| T-P-4 | REQ-2: by `someapp[bot]`, not in BOTS, `type=Bot` | `bot-actor` |
| T-P-5 | REQ-2: by `pat-machine-user`, `type=User`, in BOTS **and** in CO | `bot-actor` (the denylist wins) |
| T-P-6 | REQ-2: by `alice`, `type=User`, not in CO | `not-codeowner` |
| T-P-7 | REQ-2: by `alice`, body `authorized by ScottThurlow` followed by the form | `not-codeowner` |
| T-P-8 | AM-3: a login in CO only via a working-tree file. `decide` receives the default-branch set without it | `not-codeowner` (the CLI-level version is T-CLI-9) |
| T-P-9 | REQ-4: an edited act (`updated != created`) | `edited`, unmet |
| T-P-10 | REQ-4: a deleted act is absent from the input, with an older decline present | unmet (`declined`) |
| T-P-11 | REQ-4: `wrong-step`: `step=4` when 5 is required, and no other act | `wrong-step`, unmet. Variant: a step-4 act newer than a valid step-5 act leaves step 5 authorized |
| T-P-12 | REQ-4/REQ-5: `stale`: the act's binding ≠ B | `stale`, covered `()` |
| T-P-13 | REQ-8: authorize(t1) then decline(t2) | unmet; refusals `superseded`, `declined` |
| T-P-14 | REQ-8: decline(t1) then a current authorize(t2) | authorized; refusal `superseded` for t1 |
| T-P-15 | REQ-8: a malformed newest CODEOWNER comment (bad binding) after a valid act | unmet; `malformed-latest`, detail `bad-binding` |
| T-P-16 | AD-4: equal `created_at`; the higher id is a decline, the lower an authorize. Inputs in reverse order | unmet (ordered by id) |
| T-P-17 | REQ-6: `reviewed_files` absent / empty list / only non-diff paths | `no-overlap` ×3 |
| T-P-18 | REQ-6: `./scripts/x.py` and `"scripts/x.py"` match; `scripts/` (prefix), `x.py` (basename) and `Scripts/x.py` (case) do not | match ×2, `no-overlap` ×3 |
| T-P-19 | REQ-6 / SPEC-267 table, ported from TD-267 §3: AC-1 overlap → accepted; AC-2 non-overlap → `no-overlap`; AC-3 absent → `no-overlap`; AC-4 empty → `no-overlap` | as listed |
| T-P-20 | AD-10: a mixed set of 7 candidates (bot, non-CO, wrong-step, edited, malformed, superseded, governing accept) plus 3 non-candidates | exactly 6 refusals, 1 accepted, and none for the non-candidates |
| T-P-21 | REQ-7: the act covers `C10:new-user-flow-or-route`; required `[C10:new-user-flow-or-route, BF:dep-mapper-low]` | covered 1, unmet `BF:dep-mapper-low`, not authorized |
| T-P-22 | REQ-7/AM-6: the act covers `C10:a`; required `[C10:a, C10:b]` | `C10:b` unmet |
| T-P-23 | §4.6.1: a valid authorize(t1), then a decline(t2) edited into `hello` | unmet; governing reason `edited`, detail `non-candidate` |
| T-P-24 | §4.6.1: a valid authorize(t1), then an edited decline(t2) whose body now says `step=99` | unmet, `edited` |
| T-P-25 | §4.6.1: an edited ordinary comment *older* than a valid act | authorized |
| T-P-26 | No accumulation: authorize(t1) covers `C7`; current authorize(t2) covers `BF:x`; required `[C7, BF:x]` | `C7` unmet |
| T-P-27 | `user=None` posting the form | `not-codeowner` |
| T-P-28 | Preconditions: empty `codeowners`, empty `bots`, empty `required` or invalid `binding` | `ValueError` |
| T-P-29 | Purity: `decide` passes with `socket.socket`, `subprocess.run`, `open` and `time.time` monkeypatched to raise | passes |
| T-P-30 | NG3b (AD-1): a CODEOWNER comment whose first line is `Authorization required: release v0.7.0` | not a candidate; no refusal, no act |

### 7.2 `test_human_authorization_parse_render.py`

| Id | Case | Expect |
|---|---|---|
| T-PR-1 | Round trip: `parse_act(render_form(s, B, items, files)) == Act(...)` over a table of 6 item/path mixes | equal |
| T-PR-2 | Round trip inside ` ```text ` fences, with CRLF line endings, and with a leading BOM | equal |
| T-PR-3 | One row per `PARSE_ERRORS` code, each built to hit that code first | the code (and `@L<n>` or `:key`) |
| T-PR-4 | Not candidates: `""`, whitespace only, `hello`, `/hostile`, ` ``` ` with no content, a fence whose first line is `hello` | `None` |
| T-PR-5 | Candidacy is case-insensitive: `/HOS Authorize step=5 …` | `ParseError("marker-line")` |
| T-PR-6 | Free text after `---` is accepted. Text after `---` that contains `/hos decline` is ignored | Act |
| T-PR-7 | A decline carrying `binding=` | `unknown-key` |
| T-PR-8 | `render_form` raises on an empty `files`, an empty `items`, a bad item, or an unrepresentable path | `ValueError` |
| T-PR-9 | `render_request`: contains the issue URL, the PR URL when given, the fenced form, the decline line, the edit warning and the BF lines. Contains none of `.claudetmp/`, `-human-authorization.md` or the five ADR-1928 AD-9 strings, even when a finding's description contains `hos-escalation` | as listed |
| T-PR-10 | `render_request(parse_error=…)` includes the malformed notice with the code only | present; no body text |
| T-PR-11 | Privacy: for 20 malformed bodies containing a sentinel string `SECRET-xyz`, `detail_text()` never contains it | holds |
| T-PR-12 | Every signal name the classifier can emit matches the `C10:` syntax. The names are read from `change_classifier.py` **as source text through `ast`/regex, never imported** (`ADDED_LINE_SIGNATURES` names plus the literal `"signal": "…"` values) | all match `KEBAB` |

### 7.3 `test_human_authorization_binding.py` (real git in `tmp_path`)

| Id | Case | Expect |
|---|---|---|
| T-B-1 | The binding has the form `patch:<40hex>`. `diff_files` sorted; a rename lists both paths | holds |
| T-B-2 | ESC-3: merging `main` (an unrelated file changed) into the step branch keeps the binding | equal |
| T-B-3 | REQ-5: a new step commit changes the binding | differs |
| T-B-4 | AF-6: a whitespace-only commit changes the binding | differs |
| T-B-5 | Hostile config (AD-5 test). `HOME` points to a dir with the §4.7 hostile `.gitconfig`. Hostile repo-local config. `.gitattributes` with a textconv driver whose command writes a sentinel file. Env `GIT_CONFIG_PARAMETERS="'diff.algorithm'='patience'"`, `GIT_CONFIG_COUNT=1/KEY_0=diff.context/VALUE_0=0` and `GIT_DIFF_OPTS=--unified=0` | same id as clean; the sentinel file never created |
| T-B-6 | Two different binary payloads at one path give different ids. The same holds with `.git/info/attributes` `* -diff` | differs ×2 |
| T-B-7 | The argv recorded through a `_run_git` spy contains every ADR flag (`--no-ext-diff --no-textconv --no-color --no-renames --full-index --binary`, `diff.algorithm=myers`, `core.quotePath=true`) and never `--text` or `-a` | holds |
| T-B-8 | Missing base / missing head / shallow clone / empty diff / two merge bases (criss-cross fixture) | `git-failure` ×3, `empty-diff`, `ambiguous-merge-base` |
| T-B-9 | A path with a tab, and a path that is invalid UTF-8 (`os.fsencode` bytes name) | `unrepresentable-path` |
| T-B-10 | `base` = `--output=x` is rejected before git runs (CLI exit 2); `head` not 40-hex is exit 2 | holds |

### 7.4 `test_human_authorization_fetch.py` (fault injection: one case per exit-3 cause, REQ-9)

A recording fake replaces `_run_gh_get` and maps endpoint to response or exception.

| Id | Case | Expect |
|---|---|---|
| T-F-1 | Happy path: the exact endpoint sequence is recorded, `per_page=100&page=k` is literal, `ref=` is URL-quoted, and there is no `--paginate`. A spy on `subprocess.run` checks the argv | holds |
| T-F-2 | Only `--issue` and `--pr` comment endpoints are read. A comment on issue 99 is never requested (REQ-4 "another issue") | holds |
| T-F-3 | `gh` non-zero (404 JSON on stdout, rc=1), so the stdout is not parsed | `api-error` |
| T-F-4 | `TimeoutExpired` | `timeout` |
| T-F-5 | `OSError` (gh missing) | `api-error` |
| T-F-6 | Rate limit (rc=1, stderr `API rate limit exceeded`) | `api-error`; stderr not in the JSON |
| T-F-7 | Fake clock passes `FETCH_BUDGET_SECONDS` | `budget-exhausted` |
| T-F-8 | Page 10 full on the issue; and page 10 full on the PR | `pagination-bound` ×2 |
| T-F-9 | Page 2 is a dict, not a list | `payload-shape` |
| T-F-10 | A comment with a bad `created_at`, a non-int id, a missing `body`, `user.login` not a str, or a duplicate id across sources | `payload-shape` ×5 |
| T-F-11 | Repo metadata with no `default_branch` | `default-branch-unreadable` |
| T-F-12 | CODEOWNERS 404 / `encoding != base64` / invalid UTF-8 | `codeowners-unreadable` ×3 |
| T-F-13 | Default-branch `machine-accounts.env` 404 | `machine-accounts-unreadable` |
| T-F-14 | No partial decision: in every case T-F-3 to T-F-13, `decide` (spied) is never called | holds |

### 7.5 `test_human_authorization_cli.py`

In-process `main(argv)` with seams faked. One subprocess smoke test (T-CLI-1) runs the real module.

| Id | Case | Expect |
|---|---|---|
| T-CLI-1 | `python3 -m scripts.framework.human_authorization verify` with no args, cwd = repo root | exit 2, stdout empty |
| T-CLI-2 | Every usage rule in §4.9 (each bad flag, `--pr == --issue`, `--audit-on-change` with `--consumer evaluator`) | exit 2, no audit call |
| T-CLI-3 | Exit 0: a valid act, so the JSON keys equal the §4.9 set exactly. `verdict=authorized`, one `human-authorization` event | holds |
| T-CLI-4 | Exit 1: a decline | `not-authorized`, one refused event `declined` |
| T-CLI-5 | Exit 3 for each `ERROR_CODES` member reachable from the CLI (via the fakes): exactly one api-failure event, `refusals == []`, `covered == []` | holds |
| T-CLI-6 | REQ-9: local `machine-accounts.env` absent; present but unreadable (mode 000, or invalid UTF-8) | exit 3 `machine-accounts-unreadable` |
| T-CLI-7 | Bots empty after the union (both files with no bot keys, `BOT_ACCOUNTS` unset) | exit 3 `bot-accounts-empty` |
| T-CLI-8 | Default-branch CODEOWNERS with only team entries | exit 3 `codeowners-empty` |
| T-CLI-9 | AM-3: the working-tree `.github/CODEOWNERS` lists `alice`, the default-branch copy does not, and `alice` posts a valid act | exit 1 `not-codeowner` |
| T-CLI-10 | REQ-10: every event carries exactly the §4.10 field set for its kind. The events are written in `(created_at, id)` order. The real `audit_log` writes to `tmp_path`, and the files are read back | holds |
| T-CLI-11 | AD-10: the acceptance write fails, so exit 4, `covered == []`, `verdict=audit-failed`. A refusal write fails, so the exit is unchanged and stderr shows the WARN | holds |
| T-CLI-12 | Exit 1 with partial coverage: the acceptance write fails, so exit 4 and `covered == []` | holds |
| T-CLI-13 | `--audit-on-change`: the first call writes and records; the second identical call writes nothing (`suppressed=true`) with the same exit; a changed refusal set writes again; a failed write leaves the record not updated | holds |
| T-CLI-14 | A forged record (fingerprint of an "authorized" verdict) while the live verdict is a decline | exit 1; the record only suppresses when it matches |
| T-CLI-15 | `binding` subcommand output equals `compute_binding`; `render-request` with `--verdict-file` carrying `malformed-latest` includes the notice | holds |
| T-CLI-16 | Import graph (AM-2): `ast`-walk the module, collecting `Import` and `ImportFrom` names. Every name is stdlib (`sys.stdlib_module_names`) or one of the two framework modules. No `scripts.automation` or `scripts.oversight` import. The only `scripts.oversight` text is the `-m` argv string | holds |
| T-CLI-17 | Determinism: the same fakes give the same JSON except for `verification_id` and `verified_at` | holds |

### 7.6 Coverage of ADR §4 "Test obligations" (S1)

| ADR S1 obligation | Tests |
|---|---|
| REQ-2 table: accept a CODEOWNER; refuse the human-proxy, the worker, an unlisted `[bot]`, a `User` in BOT_ACCOUNTS, a non-CODEOWNER, and a body naming the CODEOWNER | T-P-1 to T-P-7 |
| A CODEOWNER only in the working-tree file is refused | T-P-8, T-CLI-9 |
| REQ-4: edited, deleted, other issue, wrong-step, stale | T-P-9, T-P-10, T-F-2, T-P-11, T-P-12 |
| REQ-8: authorize→decline unmet; decline→authorize met; malformed newest gives `malformed-latest`; ties by id | T-P-13 to T-P-16 |
| REQ-6: empty/absent/non-overlapping refused; `./` matches; prefix and basename do not; SPEC-267 fixtures | T-P-17 to T-P-19 |
| REQ-7: an act covering `C10:x` leaves `BF:y` unmet | T-P-21, T-P-22 |
| REQ-9: one fault-injection case per exit-3 cause, including the pagination cap | T-F-3 to T-F-13, T-B-8, T-B-9, T-CLI-5 to T-CLI-8 |
| Binding: hostile `.gitconfig`; whitespace-only changes it; a clean merge keeps it | T-B-5, T-B-4, T-B-2 |
| Render/parse round trip | T-PR-1, T-PR-2 |
| Audit: one event per candidate, every field present; acceptance failure gives exit 4 | T-P-20, T-CLI-10, T-CLI-11 |
| Import graph | T-CLI-16 |
| NG3b separation (AD-1; the verifier half) | T-P-30 |
| `parse_codeowners_humans` byte-identical | `test_requester_trust.py` §3.4 |

---

## 8. Traceability

| Requirement / decision | Section | Tests |
|---|---|---|
| REQ-1(a) / AD-1 form | §4.4 | T-PR-* |
| REQ-2 / AD-3 / AM-3 | §4.6, §4.8, §4.9 steps 4-5 | T-P-1 to T-P-8, T-CLI-6 to T-CLI-9 |
| REQ-3 / AD-2 / AM-2 | §2, §4.1, §4.9 | T-CLI-1 to T-CLI-5, T-CLI-16 |
| REQ-4 / AD-4 / AM-1 | §4.6, §4.6.1, §5 | T-P-9 to T-P-16, T-P-23 to T-P-25 |
| REQ-5 / AD-5 / AM-4 / ESC-3 | §4.7 | T-B-* |
| REQ-6 / AD-8 / AM-5 | §4.5, §4.6 | T-P-17 to T-P-19 |
| REQ-7 / AD-8 / AM-6 / ESC-4 | §4.2 `ITEM_RE`, §4.6 | T-P-21, T-P-22, T-PR-12 |
| REQ-8 | §4.6 | T-P-13 to T-P-16 |
| REQ-9 | §4.7, §4.8, §6 | §7.4, T-CLI-5 to T-CLI-8 |
| REQ-10 / AD-10 / AM-7 | §4.10, §4.11 | T-CLI-10 to T-CLI-14, T-P-20 |
| AD-6 `--audit-on-change` | §4.11 | T-CLI-13, T-CLI-14 |
| AD-9 render (S3 caller) | §4.4 `render_request`, §4.9 | T-PR-9, T-PR-10, T-CLI-15 |

---

## 9. pm-agent's open points: resolutions

1. **REQ-10 "audit every verdict" versus AD-6 `--audit-on-change`.** **Resolved: S1 implements the flag** (§4.11). The reason is that S2's file list does not include the verifier, so the flag must exist before S2. It is legal only with `--consumer overseer` (exit 2 otherwise). The evaluator and `pr-readiness` therefore always audit every verdict, which is REQ-10 as written. The overseer's suppression is the AD-6-sanctioned exception. It only skips re-recording a verdict *this clone already recorded* with an identical fingerprint, and the record is updated only after every write succeeds, so "every distinct verdict is recorded" holds. Classification: clarifying.
2. **A valid decline: event type and decision versus AD-10 listing `declined` as a refusal reason.** **Resolved.**
   - A governing decline by a verified CODEOWNER yields `human-authorization-refused` with `reason: "declined"`, and JSON `act.decision = "decline"`. The decline is a valid act, and its effect is that nothing is authorized.
   - `human-authorization` is reserved for a *valid governing authorize*, with `decision: "authorize"`. A researcher counting `human-authorization` events therefore counts authorizations only. The existing `decision` field keeps its name and is always `"authorize"` in v1.
   - An older decline superseded by a later authorize is `superseded`.
   - Classification: clarifying. pm-agent may wish to align REQ-10's wording.
3. **An unreadable `machine-accounts.env` must be exit 3 (REQ-9).** **Resolved, for both copies** (§4.9 step 4, §4.8 read 3):
   - the local file absent, or present but unreadable or undecodable;
   - the default-branch copy 404 or undecodable;
   - the union empty (`bot-accounts-empty`).

   Tests: T-CLI-6, T-CLI-7, T-F-13. Consumer prerequisite noted in §4.8.
4. **How a malformed newest comment's parse error surfaces.** **Resolved.**
   - It is exit 1, and `error` stays `null`: the decision was made on complete data.
   - The `refusals[]` entry has `reason: "malformed-latest"` and `detail: "<code>[@L<n>|:<key>]"`. `act.decision` is `"malformed"`.
   - `render-request --verdict-file` turns that entry into the human-facing notice (§4.4 item 6).
   - The detail is a closed code plus a line number, never body text (privacy, T-PR-11).
5. **The Condition 14 consumer.** **Note only: an S2 concern.** S1 serves it with the same `--require C10:<signal>…` call (AD-6). Nothing in S1 is specific to condition 14.

**Also noted for pm-agent (wording, no behaviour change):** REQ-10 lists "the step and the binding (head SHA)". Under AM-4 the binding is the patch-id. The events carry `binding` (`patch:<hex>`) **and** `head_sha` separately (§4.10), so both readings are recorded.

---

## 10. Questions for the architect

Each question gives this TD's default, which S1 is drafted on, and what changes under the alternative.

| Id | Question | TD default | Class |
|---|---|---|---|
| **ARCH-Q1** | **Deletion resurrection (R-S1-5).** A bot with `issues: write` deletes a human's newer `/hos decline`. The older authorize, still current, then governs. AD-4 considered deleting an *authorize* (closed) but not deleting a later *decline*. Mitigation would read GraphQL `CommentDeletedEvent` (`deletedCommentAuthor`, `createdAt`) on the issue and PR, and treat a deletion of a CODEOWNER's comment newer than the governing act as poison (unmet, new reason `deleted-later`). That adds a second transport and fetch to the trust path, which is an architecture decision. | **Not mitigated in S1; stated as R-S1-5.** The older act still names the current binding, so the content is something the human did approve once, and the deletion is visible in the GitHub UI. If you rule "mitigate": +1 fetch in §4.8, +1 reason, +3 tests, same files. | Architecture (security) |
| **ARCH-Q2** | **§4.6.1 edit rule.** Any edited verified-CODEOWNER comment newer than the latest act voids it, whatever its body. This closes the edit-to-non-candidate and edit-to-other-step resurrection attacks. It is user-visible: the human cannot edit a later comment on the step issue or PR without re-authorizing. | Adopted (fail closed). The alternative, "only edited candidates poison", reopens the two attacks. | Additive; user-visible, so pm-agent should be aware |
| **ARCH-Q3** | **Closed-set additions to AD-10:** reason `superseded`; fields `detail`, `unmet`, `overlap`, `verification_id`, `comment_issue`, `head_sha`, `base_sha`, `merge_base`; JSON `act.decision`, `audit`, `exit_code`, `schema`. All are compatible extensions. Without `superseded`, AD-10's "one event per candidate" cannot hold for older valid acts. | Adopted | Additive |
| **ARCH-Q4** | **ADR internal tension for S2:** AD-2 says "only 0 clears an item", while AD-6 says the evaluator may make one call with the union of items and "split per item from `covered[]`". S1 guarantees that `covered[]` is non-empty only on exit 0, or exit 1 with the acceptance event written (§2 rule 6). That makes the per-item split safe on exit 1. | S1 supports both. **S2 needs your ruling.** I recommend allowing the split on exit 0 or 1 only. | Clarifying (S2) |
| **ARCH-Q5** | Two extra extractions in `requester_trust.py` (`parse_env_text`, `bot_baseline_from_env_text`) beyond the ADR's "extraction only: `parse_codeowners_humans`" (§3). | Adopted | Clarifying |
| **ARCH-Q6** | Grammar refinements inside AD-1's delegation: case-insensitive candidacy (a near-miss is reported as malformed, not ignored); an optional enclosing code fence, because AD-9 presents the form fenced and humans copy the fences; CRLF and BOM normalization; `reviewed_files:` absent is `no-overlap` (AD-8) rather than `malformed`. | Adopted | Additive |
| **ARCH-Q7** | The AD-4 GraphQL `lastEditedAt` alternative pass condition is **not adopted** (§5.3: it would accept hidden comments). R-S1-1 (a same-second edit) is accepted unmitigated. | Adopted | Clarifying |

None of these blocks handing S1 to `coder` once you approve. ARCH-Q1 changes S1's scope if you rule "mitigate".

---

## 11. Startup-gap check and affected sign-offs

- **Should this have been settled in the initial design?** The startup gap for #2101 as a whole is already recorded in ADR-2101 §6, with a recommendation to open or annotate a `startup-artifact-gap` issue. This TD is the first design of S1, not a reactive change to an approved contract, so it raises **no new startup gap**.
- **Affected sign-offs.** None. No code has been approved against an earlier S1 contract.
  - The `requester_trust.py` extractions are behaviour-identical, and their tests pin that. The #1540 S1 sign-offs on `requester_trust.py` stand.
  - The one conformance test edited (§3.4) widens an allow-set by one *delegating* reader, with stronger assertions, so the #1540 sign-off on that test stands.
  - `security-reviewer` should still confirm, on the S1 PR, that `codeowners_humans` and `load_bot_accounts` are unchanged.

---

## Escalation flag (CORE self-flag)

RISK: HIGH. This module becomes the sole decision point for the CRITICAL and structural human gates, on a protected surface. A defect in `decide` (§4.6), the actor rule or the binding is a bot-satisfiable gate.
CONFIDENCE: HIGH on the reuse citations, the binding behaviour (local experiment, §4.7) and the probe results (§5, live reads this session). MEDIUM on ARCH-Q1's real-world exposure: I did not probe REST or GraphQL deletion-event visibility.
BLAST RADIUS: in S1, none at runtime: the module has no caller. Two `requester_trust.py` functions are refactored behind unchanged signatures. One conformance test is widened. In S2, every gated step's path to a PR.
Change classification: **additive** (S1). It implements a human-approved STRUCTURAL ADR. The refinements in §10 are additive or clarifying. ARCH-Q1 and ARCH-Q2 are routed rather than decided silently.

## Human Review Required

The S1 PR lands on `scripts/framework/**`, so your own-account approval of the protected-surface PR is the final gate. Before then, the architect must answer ARCH-Q1 (deletion resurrection), and should confirm ARCH-Q2 (any later edit voids the act, which is user-visible). REQ-2 and REQ-9 are not open to any answer.
