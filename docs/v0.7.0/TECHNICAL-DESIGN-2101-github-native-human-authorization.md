# TECHNICAL DESIGN — #2101 slice S1: the inert GitHub-native human-authorization verifier (`scripts/framework/human_authorization.py`)

**Status:** APPROVED WITH CHANGES by architect, round 1 (2026-10-22). Rulings and the changes applied are in §10.1. Ready for `coder` (S1 only).
**S1b status (§10.4, #2151):** DRAFT, 2026-10-30. Awaiting architect review. **ARCH-Q-S1b (the transport for the deletion read) is open.** Not for `coder` until it is ruled.
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

**S1b (§10.4) adds no file.** It edits files 1, 3, 5, 6, 7 and 10, plus this TD. All are already on the branch, which stays at 14 files.

---

## 2. Organizing rules (checks the coder can verify)

1. **Purity boundary.** `parse_act`, `render_form`, `render_request`, `canonicalize_path`, `parse_item`, `decide` and `fingerprint` read no clock, no environment, no file and no network. `parse_codeowners_humans`, `parse_env_text` and `bot_baseline_from_env_text` in `requester_trust` are equally pure.
2. **Three I/O seams, and only three.** Each is a module attribute that tests monkeypatch:
   - `_run_gh_get(endpoint) -> Any`: all GitHub reads.
   - `_run_git(repo_root, args, *, stdin=None) -> bytes`: all git.
   - `_audit_write(event, audit_root) -> bool`: the audit subprocess.

   Nothing else in the module spawns a process or opens a socket.

   **S1b (§10.4.4; ARCH-Q-S1b ruled G by R-A8, §10.4.9):** a fourth seam, `_run_gh_graphql(owner, name, number, after) -> Any`, carries the one read-only GraphQL query, `DELETIONS_QUERY`, and nothing else. After S1b the rule reads "four I/O seams, and only four".
3. **No decision on incomplete data.** `decide` runs only after every input is complete: the binding, the diff file list, both CODEOWNERS and bot sources, and every comment page from every source. Any failure before that point is exit 3, with `covered == []` and `refusals == []`.
4. **Nothing in a clone confers authority.** The verifier never reads `.github/CODEOWNERS` from disk, and never reads any `.claudetmp/**` auth file. The one local file it writes besides audit records is the `--audit-on-change` suppression record (§4.11). That record can only suppress an audit write. It is never read to compute a verdict.
5. **Import graph (AM-2).** The verifier imports only the standard library, `scripts.framework.require_human_approval` and `scripts.framework.requester_trust`. It contains no `scripts.automation` and no `scripts.oversight` import. `audit_log` is reached only as `python3 -m scripts.oversight.lib.audit_log` in a subprocess argv.
6. **Only exit 0 means authorized.** `covered[]` is non-empty only when the exit is 0 or 1 **and** the acceptance audit event was written (§4.10). On exit 2, 3 or 4, `covered` is `[]`. The per-item consumer rule built on this is §10.1 R-A2.

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

**Superseded by architect ruling R-A7 (§10.3): the body is tightened, not moved verbatim.** For each line of `text.splitlines()`:
1. Strip it. Skip the line if it is blank or starts with `#`. (A line starting with `\#` is a path, not a comment.)
2. **Path token.** Scan from column 0. A `\` escapes the next character, so `\ ` and `\#` belong to the path. The path ends at the first unescaped whitespace character. If there is no rest, the line has no owners.
3. **Owner tokens.** `rest.split()`, in order. **Stop at the first owner token that contains a `#`** (amended 2026-11-18, R-A7a, §10.3). That token is not accepted either, even if the text before its `#` would be a valid `@login`. `#` is never valid in a login, team or email, so such a token is either an inline-comment start (`#x`, `@alice#`) or malformed (`@a#x`), and the strict parser must never yield an owner that a first-`#` resolver would not. For each token before that:
   - skip it unless it starts with `@`. This drops emails and bare words;
   - skip it if it contains `/` (a team `@org/team`);
   - add `token[1:].lower()` iff `token` fullmatches `OWNER_LOGIN_RE = re.compile(r"@[A-Za-z0-9][A-Za-z0-9-]{0,38}")`. Otherwise skip it.
4. Return the set. The output contract is unchanged: lowercased logins with `@` stripped, and team handles never included.

Skipping a token never raises; a CODEOWNERS file that ends with no humans is handled by each caller's existing empty-set path. The `codeowners_humans` docstring drops "byte-identical behaviour". It says instead that the tightening follows R-A7.

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

- **R-A7 tightening (§10.3).** Add `TestParseCodeownersHumansStrict`, one assertion per row:
  - `* @maintainer # alice handles triage` gives `{"maintainer"}`;
  - `* @a #comment @b` gives `{"a"}`;
  - `* @a#x` gives `set()` (the token contains `#`, so the owner list ends there);
  - `* @alice# see @bob` gives `set()` (R-A7a: `@alice#` ends the list; `@bob` is comment text);
  - `* @org/team# ask @bob` gives `set()` (R-A7a: a team token carrying `#` also ends the list);
  - `* @alice @bob#x @carol` gives `{"alice"}` (R-A7a: owners before the `#` token stand; the `#` token and everything after it are dropped);
  - `docs/My\ File.md @alice` gives `{"alice"}` (`File.md` is not an owner);
  - `\#notes.md @bob` gives `{"bob"}` (an escaped `#` path is not a comment);
  - `* alice@example.com bob @carol` gives `{"carol"}`;
  - `* @org/team @dave` gives `{"dave"}`;
  - `* @-bad @` plus a 40-character login gives `set()`;
  - a 39-character login is accepted;
  - **the repository's real `.github/CODEOWNERS`** gives exactly the set the pre-R-A7 parser gave (`{"scottthurlow"}`). This pins that no real owner is dropped.

  Add `test_inline_comment_owner_cannot_authorize` in `test_human_authorization_predicate.py`. It parses the codeowners set from `* @maintainer # alice handles triage` with `parse_codeowners_humans`, then runs `decide()`. An otherwise-valid, unedited, current-binding `authorize` act by `alice` (not a bot) is **not** authorized: no item is covered, and the refusal reason is the one §4.6 gives a non-CODEOWNER. The same act by `maintainer` **is** authorized.
- **Pin.** Add `TestParseCodeownersHumans`, which runs every existing `TestCodeownersHumans` case (`:97-139`) through `parse_codeowners_humans(text)` and asserts the same sets. Every existing case remains valid under R-A7; the coder confirms this, and any case that changes is a stop-and-escalate. Add `TestBotBaselineFromEnvText` with the four keys and the `BOT_ACCOUNTS=` line, which is ignored. Assert that `load_bot_accounts` results for the existing `TestLoadBotAccounts` cases (`:189-236`) are unchanged.
- **Required update, or S1 breaks the suite.** `TestConformance.test_no_second_codeowners_parser_in_framework` (`:663-684`) asserts that the set of `scripts/framework/*.py` files containing the string `CODEOWNERS` is exactly `{requester_trust.py, select_work_candidates.py}`. The verifier must name `.github/CODEOWNERS` in its contents-API endpoint, so it trips this test.
  - The coder adds `scripts/framework/human_authorization.py` to the expected set.
  - The coder adds `assert "parse_codeowners_humans(" in ha_text`.
  - **(Architect ruling R-A4, replacing the round-1 assertions.)** The coder adds `assert re.search(r"(?<![A-Za-z0-9_])codeowners_humans\(", ha_text) is None` (the working-tree reader is never called, in any spelling) and `assert "_codeowners_path" not in ha_text`, and asserts that every line of `ha_text` containing the literal `CODEOWNERS` is either the `CODEOWNERS_PATH = ".github/CODEOWNERS"` assignment, a comment/docstring line, or a line that also contains `contents/`. The round-1 `"read_text" not in ha_text` ban is **dropped**: `render-request --findings-file/--verdict-file` and the §4.11 record legitimately read files, and a string ban on `read_text` only invites `open()` workarounds. The behavioural guard that the verifier never reads CODEOWNERS from disk (AF-2) is T-CLI-9, which is mandatory.

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
   - If the stripped line starts with `reviewed_files:` (a prefix match, as for `covers:`):
     - if anything other than whitespace follows the colon (e.g. `reviewed_files: foo.py`), return `unexpected-line@L<n>`. Paths go only on `  - <path>` lines below the header;
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
2. `**Action:** copy only the text inside the first box below into a new comment, from your own GitHub account. Its first line must be the /hos line. Delete any reviewed_files line for a file you did not review, but keep at least one.` *(Architect ruling R-A5: a human who pastes the whole request block makes a comment whose first line is `### Action needed`, which AD-1 ignores silently. The instruction must say "only the box", and that the first line is the `/hos` line.)*
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

**Amended by S1b (§10.4.5).** `decide` gains a required keyword-only argument `deletions`, and the accept branch gains the `deleted-later` check.

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

`sorted(refusals)` orders by `(created_at, comment_id)`, via an explicit `key=` (the dataclasses are not declared `order=True`). Every candidate comment yields **exactly one** of: one `Refusal`, or the `Accepted`. This is AD-10's "one event per candidate", and T-P-20 pins it. The only non-candidate that yields an event is a governing edited non-candidate (§4.6.1).

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

**Amended by S1b (§10.4.6).** Every git call in `compute_binding` goes through `_git_budgeted`, which enforces a per-call `BINDING_BUDGET_SECONDS` deadline. The old-blob cache is hoisted out of the rung loop. Patch and blob bytes are capped (`patch-too-large`).

**`_run_git(repo_root, args, *, stdin=None) -> bytes`.**
- argv is `["git", "-C", str(repo_root), f"--attr-source={EMPTY_TREE}", *GIT_PIN, *args]`, where `EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"` (the SHA-1 empty tree). **Architect ruling R-A3 (§10.1):** this stops git reading `.gitattributes` from the **working tree** (or index). Without it, a working-tree `* -diff` (or `binary`) attribute changes the patch-id (architect experiment, git 2.53.0: clean `427de3d6…`, worktree `* -diff` `1656691d…`, worktree `* -diff` with `--attr-source=<empty>` `427de3d6…`). The worker computes on the step branch and the overseer on the default branch, so a step that edits `.gitattributes` would otherwise give the two clones different bindings: a permanent `stale` that no human act can clear. `$GIT_DIR/info/attributes` is still read (R-S1-2 stands, per clone). <!-- pragma: allowlist secret -->
- **`--no-replace-objects` (second review, codex, CWE-345; §10.2).** Every invocation also passes git's global `--no-replace-objects` before the subcommand (argv order: `-C`, `--no-replace-objects`, `--attr-source=…`, pins, subcommand), so `refs/replace/*` in the clone cannot substitute objects for the supplied `head` or `base`. `GIT_NO_REPLACE_OBJECTS` and `GIT_REPLACE_REF_BASE` are `GIT_*` keys and stay stripped.
- **Minimum git version.** The verifier needs `patch-id --verbatim` and `--attr-source` (git ≥ 2.42). An older git rejects the option, so the call exits non-zero and is `git-failure` (exit 3, closed). The coder records the exact minimum version in the module docstring; S2 adds it to the consumer prerequisites (§10.1, S2-PRE-3).
- `env` is built from `os.environ`, minus **every key starting with `GIT_`**. This removes `GIT_DIR`, `GIT_WORK_TREE`, `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`/`KEY_n`/`VALUE_n`, `GIT_DIFF_OPTS`, `GIT_EXTERNAL_DIFF` and `GIT_ATTR_SOURCE`. Three keys are then added: `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1` and `GIT_ATTR_NOSYSTEM=1`.
- Use `capture_output=True`, `timeout=GIT_TIMEOUT_SECONDS` and `check=False`. When no `stdin` bytes are passed, stdin is `subprocess.DEVNULL` (§10.2).
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
   **Context ladder (architect ruling R-A6, §10.3).** `--unified=3` is only the first rung. `CONTEXT_LADDER = (3, 10, 30, 100, 2147483647)`. For each `n` in order, `patch_n` is the argv above with `--unified=<n>` and no other change. The first `patch_n` for which `_hunks_anchored(repo_root, patch_n)` (step 5a) is true is the `patch` used by steps 6 and 7. The last rung is whole-file context, where every hunk is the whole old file, so anchoring holds by construction. If it is still false there, raise `git-failure` (closed; unreachable with real git). The rung is **not** encoded in the binding: the verifier recomputes it deterministically from `(merge_base, head)`.
5a. **`_hunks_anchored(repo_root, patch) -> bool`** (R-A6). This is true iff the pre-image of every text hunk occurs **exactly once** in that file's old blob. `git patch-id` drops hunk positions (the `@@` line numbers). Uniqueness puts the position back: when a hunk's pre-image occurs once in the old blob, the hunk text alone fixes where it applies.
   - Split `patch` on `b"\n"`. A section starts at each `diff --git ` line. The old blob id is the left side of the section's first `index <old>..<new>[ <mode>]` line. It must fullmatch `SHA_RE`, otherwise `git-failure`. All zeros means the old blob is empty (a new file).
   - A section in which any extended-header line ends in ` 160000` (a gitlink) is skipped. Its one `Subproject commit` line is the whole value, so it has no position. A section with no `@@` line (binary, mode-only) is skipped too: a `--full-index --binary` patch is a whole-blob transformation.
   - A hunk header is `@@ -a[,b] +c[,d] @@`, with `b` and `d` defaulting to 1. Read body lines until `b` pre-image lines (` ` or `-`) and `d` post-image lines (` ` or `+`) have been seen. A line starting with `\` is skipped. Any other line, or running out of lines, raises `git-failure`.
   - The pre-image is the hunk's ` ` and `-` lines, in order, each with its 1-byte tag stripped.
   - The old blob is read once per id, via `_run_git(["cat-file", "blob", old_id])`. A failure (for example, a non-blob id) is `git-failure`, closed.
   - Count line-aligned occurrences with `bytes.find` and stop at 2. `hay = b"\n" + blob + (b"\n" if blob and not blob.endswith(b"\n") else b"")` and `needle = b"\n" + b"\n".join(pre) + b"\n"`. Overlapping matches count, so the next search starts at `pos + 1`. This ignores the "no newline at end of file" distinction, which can only overcount (safe).
   - An empty pre-image counts 1 iff the old blob is empty, and 2 otherwise. A count of 0 (the pre-image is not in its own old blob) raises `git-failure`. A count of 2 makes the whole patch unanchored, and the caller moves to the next rung.
6. If `patch == b""` (checked on the first rung), raise `empty-diff`. A step with no diff has nothing to authorize.
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

| *(architect)* Working-tree `.gitattributes` `* -diff` | changed **without** `--attr-source`; **same** with `--attr-source=<empty tree>` (now pinned) |
| *(architect, R-A6)* `access.py` with two functions whose 7-line bodies are identical. Flip `allowed = False` to `True` in `preview_access` (A) and in `production_access` (B) | `--unified=3`: A = B = `f93042f0…` **(collision; codex CWE-345 reproduced)**. `--unified=5`: still equal. `--function-context`: distinct here. Ladder: rung 10, A `8e9ec944…`, B `a4ae3f1a…` **(distinct)** |
| *(architect, R-A6)* `gate.sh` with two identical top-level `if … fi` blocks; flip `allowed=0` in each | `--unified=3` **and** `--function-context`: A = B **(both collide, so `-W` is not a fix)**. Ladder: rung 10, distinct |
| *(architect, R-A6)* Ambiguous step (rung 10) after a clean merge of `main`, which edited the same file more than 10 lines from the hunk | **same** binding (ESC-3 holds). A `main` edit inside the rung-10 window but outside 3 lines: changed (closed, R-2) |

`.git/info/attributes` cannot be neutralized from the command line (`--attr-source` does not suppress it; architect experiment). Its only effect is to make one clone compute a *different* id (`stale`, closed), never to make two different contents collide. Tests T-B-5 and T-B-6 pin both directions.

### 4.8 Fetcher: `fetch(repo, issue, pr) -> Fetched` (AD-3, REQ-9)

**`_run_gh_get(endpoint) -> Any`** has the contract of `requester_trust._run_gh_get` (`:449-477`), re-implemented:
- argv `["gh", "api", endpoint]`;
- no `--paginate`, no `-f`/`-F`/`--method`/`--input`;
- `timeout=GH_TIMEOUT_SECONDS`;
- `stdin=subprocess.DEVNULL`, and `env` is `os.environ` plus `GH_PROMPT_DISABLED=1`, so `gh` can never wait on a prompt (§10.2).

On 404, `gh` prints the error JSON to stdout **and exits 1** (probed: `contents/.github/NOPE` gives `rc=1`). So the return code is checked **before** any parse, and non-zero is a failure.

Failures map as follows:
- `TimeoutExpired` gives `timeout`.
- `OSError` gives `api-error`.
- A non-zero exit gives `api-error`. A rate limit is the same code. `gh`'s stderr text is **never echoed** anywhere (privacy review, §10.2): the module's stderr diagnostic line is exactly `gh api exit=<rc>`, plus ` HTTP <ddd>` when an `HTTP (\d{3})` status appears in that stderr. Nothing from it reaches JSON or audit.
- Invalid JSON gives `payload-shape`.

**Deadline.** Each `fetch()` call sets its own local deadline, `deadline = time.monotonic() + FETCH_BUDGET_SECONDS`, as its first statement. It is never a module-level value computed at import, and never shared between calls. The deadline is checked before every `gh` call that `fetch()` makes. If it has passed, raise `budget-exhausted`.

**Reads, in this order** (`o/r` is `--repo`):
1. `repos/{o}/{r}` gives a dict with a non-empty str `default_branch`. Anything else is `default-branch-unreadable`.
2. `repos/{o}/{r}/contents/.github/CODEOWNERS?ref={quote("refs/heads/" + default_branch, safe='')}` (fully qualified, so a same-named tag cannot shadow the default branch; security review, CWE-345, §10.2) must give a dict with `type == "file"`, `encoding == "base64"` and a str `content`. The content is decoded with `base64.b64decode(content, validate=False)` after removing `"\n"`, then decoded as strict UTF-8. Any failure, including an `api-error` from a 404, is **`codeowners-unreadable`** (the error code is re-mapped).
3. `repos/{o}/{r}/contents/scripts/framework/machine-accounts.env?ref=…` gets the same handling, but failures are **`machine-accounts-unreadable`**. **Consumer prerequisite (note for S2/pm):** a consumer project must commit `scripts/framework/machine-accounts.env` on its default branch, or every `verify` exits 3. That is fail-closed and per REQ-9. Today's consumer installer does not ship that file (`framework_consumer_files.txt` has no entry for it).
4. `repos/{o}/{r}/issues/{issue}/comments?per_page=100&page={k}` for `k = 1 … COMMENT_PAGE_BOUND`. The endpoint string carries the query literally, as in `requester_trust.py:519`.
   - Each page must be a list; otherwise `payload-shape`.
   - A page with fewer than 100 items ends the loop.
   - If page `COMMENT_PAGE_BOUND` is full, raise **`pagination-bound`**.
   - No partial list is ever returned.
5. If `--pr` is given, step 4 is repeated for `--pr`. PR conversation comments are `/issues/{pr}/comments` (AD-1: one read path).
6. **S1b (§10.4.4): deletion reads.** After every comment read, the deletion events of the issue (and of `--pr`) are read under the same deadline. `Fetched` gains `deletions`.

**Unexpected exceptions (fail closed; §10.2).** Any exception other than `VerifierError` raised in `fetch`, the bot/CODEOWNERS steps or `decide` is mapped to `VerifierError("api-error")`: exit 3, `covered = []`, one api-failure event, and one stderr line `internal-error type=<ExceptionClassName>`. A bug can never read as exit 0 or 1.

**Comment normalization** (`_comment_from(obj, issue_number) -> Comment`): any violation raises `payload-shape`, so the decision never sees a half-understood record.
- `obj` is a dict.
- `id` is an `int > 0` and not a `bool`.
- `html_url` is a str.
- `body` is a str.
- `created_at` and `updated_at` are strs matching `TS_RE`.
- `user` is a dict, or `None`, which gives `login = ""` and `user_type = ""`. `user.login` and `user.type` are strs when present.

A comment id appearing twice across both sources also gives `payload-shape`.

**Cost.** At most `3 + 2 × 10 = 23` GETs per `verify`. S1b raises the maximum to 43 calls (§10.4.4); the typical cost rises from 4 calls to 5 without `--pr`, and from 5 to 7 with it. The worst case on this repo today is 1 page per source (the busiest issue, #2139, has 45 comments across the 2,440 read in §5).

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
- `REPO_RE`, `NUM_RE`, `SHA_RE` or `REF_RE` fails (every CLI and API input regex is applied with `fullmatch`, never `match`/`search`, so a trailing newline cannot pass `$`);
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
   - `main()` has a last-resort `except Exception` that writes `internal-error type=<ExceptionClassName>` to stderr and returns 3, so no escaped exception ends the process with a traceback exit of 1.

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
- A failed acceptance write gives exit 4 (§4.9) with `covered = []`. Acceptance writes are **always attempted**, even after a refusal write has failed.
- A failed refusal or api-failure write leaves the exit unchanged. It adds one stderr line, `human_authorization: WARN audit-write-failed event=<event> comment_id=<id|none>`, and increments `audit.failed`.
- **After the first failed refusal-event write, later refusal writes are skipped** (reliability review, §10.2: a degraded writer would otherwise stall N × `AUDIT_TIMEOUT_SECONDS`). Each skipped write is counted in `audit.failed`, so the §4.11 record is not updated, and no further WARN is printed: one WARN only.

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
| `gh` non-zero, OSError, rate limit | exit 3 `api-error`, one api-failure event; stderr shows `gh api exit=<rc>` and an optional `HTTP <ddd>` only | Closed |
| Unexpected exception in fetch or decide | exit 3 `api-error`, `covered = []`, one api-failure event; `main()` last-resort catch returns 3 | Closed |
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
| Working-tree `.gitattributes` `-diff`/`binary` (e.g. the step edits `.gitattributes`) | Neutralized by `--attr-source=<empty tree>`; same id in worker and overseer clones | — (R-A3) |
| git older than the minimum version | exit 3 `git-failure` | Closed |
| Local `.git/info/attributes` `-diff` | Different id, so `stale` | Closed (R-S1-2) |
| The same hunk text moved to another position with an identical context window (the act covered edit A; the head now carries edit B) | The context ladder escalates until every pre-image is unique, so A and B bind differently and B is `stale` | Closed (R-A6) |
| Step hunk with an ambiguous 3-line context, then `main` edits nearby | The escalated window is wider, so the binding changes more often after a merge from `main` | Closed (over-refusal, R-2 widened; R-A6) |
| Old-blob read fails or a hunk is malformed | `git-failure`, exit 3 | Closed |
| Bot edits or deletes a human's *authorize* | `edited` / absent, so unmet | Closed |
| Bot edits a human's newer *decline* into chatter or another step | Still a participant (§4.6.1), so `edited` | Closed |
| Bot **deletes** a human's newer decline | A deletion event of a CODEOWNER's comment (or one with an unknown author) at or after the governing act's creation gives `deleted-later`, so unmet, exit 1 (§10.4.5) | **Closed: R-S1-5 (S1b)** |
| A CODEOWNER's comment older than the governing act is deleted by someone else after the act | `deleted-later` | Closed (over-refusal; §10.4.5) |
| Deletion read fails: `gh` non-zero (including GraphQL `errors`), timeout, invalid JSON, wrong shape, `filteredCount` ≠ nodes collected, bad cursor, duplicate event id | exit 3: `api-error` / `timeout` / `payload-shape` | Closed (HQ-1) |
| Deletion pages exceed `DELETION_PAGE_BOUND` | exit 3 `pagination-bound` | Closed |
| A CODEOWNER deletes their **own** newer decline | Probably not recorded by GitHub (0/41 events had deleter = author; not testable read-only), so the older authorize governs | Stated residual **R-S1b-1** (the human's own act) |
| Binding phase exceeds `BINDING_BUDGET_SECONDS` (120 s) | exit 3 `budget-exhausted` | Closed (S1b) |
| A ladder rung's patch, or the old blobs read, exceed `BINDING_BYTES_MAX` (16 MiB) | exit 3 `patch-too-large` | Closed (S1b; over-refusal for very large steps) |
| Comment hidden (minimized) | `edited` | Closed (over-refusal) |
| Acceptance audit write fails | exit 4, `covered = []` | Closed |
| Refusal audit write fails | Exit unchanged, one WARN; later refusal writes skipped and counted as failed | Closed |
| Forged or corrupt `--audit-on-change` record | Writes happen, or are suppressed; the verdict is unchanged | Record-only |

**Residuals (stated).**
- **R-S1-1:** a same-second edit (§5.3).
- **R-S1-2:** a local `info/attributes` `-diff` gives an over-refusal.
- **R-S1-3:** an unrepresentable diff path blocks the step until it is renamed.
- **R-S1-4:** SHA-256 repositories are unsupported (they fail closed).
- **R-S1-5:** a decline deleted by a bot resurrects an older current authorize (ARCH-Q1). **Closed by S1b** (§10.4) under ARCH-Q-S1b option G. Under option R it is closed except for the REST listing gap (§10.4.2), which remains as R-S1b-3.
- **R-S1b-1, R-S1b-2, R-S1b-3, R-S1b-4:** see §10.4.8.
- **R-S1-6 (R-A6):** the binding pins an edit to the **unique** location of its pre-image in the merge base current at the time. Suppose a later reviewed `main` change moves that exact pre-image block verbatim elsewhere, and removes the original. A re-pointed edit with identical text then carries the binding. Exploiting this needs a reviewed `main` commit that relocates a pre-image of 7 or more lines, and the edit follows the moved code. Accepted.
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

**S1b additions (§10.4.5).** The `_decide` helper gains `deletions=()` and passes it as `deletions=deletions`. A helper `_del(eid, at, author="scottthurlow", issue=2101)` builds a `Deletion`. `A` is a valid, current, overlapping authorize by `scottthurlow` with `created="2026-10-20T10:00:00Z"`.

| Id | Case | Expect |
|---|---|---|
| T-P-31 | **R-S1-5 regression.** Comments `[A]` only (the newer decline is gone); `deletions=(_del(901, "2026-10-20T12:00:00Z"),)` | `authorized False`, `covered ()`, `unmet ("C7",)`, `accepted None`, `governing.decision "authorize"`; refusals exactly `[deleted-later, detail "event:901"]` on A's comment id |
| T-P-32 | The deletion is older than the act: `deleted_at "2026-10-20T09:59:59Z"` | authorized |
| T-P-33 | Same second: `deleted_at == A.created_at` | `deleted-later` |
| T-P-34 | Unknown author: `author=None`, after A | `deleted-later` |
| T-P-35 | Author not a CODEOWNER: `alice`, then `hos-worker-hos[bot]`, each after A. Case: `ScottThurlow` after A | authorized ×2; `deleted-later` |
| T-P-36 | The governing act is a decline (or stale, or edited), with a qualifying deletion after it | the existing reason only (`declined` / `stale` / `edited`); no `deleted-later`; refusal count as without the deletion |
| T-P-37 | Two qualifying deletions, `(950, 12:00:00Z)` and `(940, 12:00:00Z)`, plus `(930, 13:00:00Z)` | one refusal, detail `event:940` (the earliest by `(deleted_at, event_id)`) |
| T-P-38 | Recovery: A, a deletion at `12:00:00Z`, then a fresh current authorize at `13:00:00Z` | authorized by the fresh act; A is `superseded` |
| T-P-39 | Deletion on the PR source (`issue=2200`) while A is on the issue | `deleted-later` (deletions from both sources apply) |
| T-P-40 | `decide(...)` called without `deletions`; then with `deletions=("x",)` | `TypeError`; `ValueError` |
| T-P-41 | AD-10 invariant: T-P-20's mixed set plus one qualifying deletion | still one event per candidate. The governing accept becomes a `deleted-later` refusal, and nothing is accepted |

T-P-29 (purity) runs with a non-empty `deletions`.

### 7.2 `test_human_authorization_parse_render.py`

| Id | Case | Expect |
|---|---|---|
| T-PR-1 | Round trip: `parse_act(render_form(s, B, items, files)) == Act(...)` over a table of 6 item/path mixes | equal |
| T-PR-2 | Round trip inside ` ```text ` fences, with CRLF line endings, and with a leading BOM | equal |
| T-PR-3 | One row per `PARSE_ERRORS` code, each built to hit that code first | the code (and `@L<n>` or `:key`) |
| T-PR-3b | `reviewed_files:` with inline trailing text (`reviewed_files: foo.py`) is `unexpected-line@L<n>`, where `<n>` is that line, not `unknown-key`. `reviewed_files:   ` (trailing whitespace only) followed by `  - scripts/x.py` parses, with that path | `unexpected-line@L<n>`; Act |
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
| T-B-6a | R-A3: a working-tree `.gitattributes` containing `* -diff`, and separately `* binary`, written after the commits (uncommitted), gives the **same** id as clean. Variant: the step commit itself adds `.gitattributes` `* -diff`; computing from a checkout of `head` and from a checkout of `base` gives the same id | same ×3 |
| T-B-7 | The argv recorded through a `_run_git` spy contains every ADR flag (`--no-ext-diff --no-textconv --no-color --no-renames --full-index --binary`, `diff.algorithm=myers`, `core.quotePath=true`), `--attr-source=4b825dc642cb6eb9a060e54bf8d69288fbee4904` before the subcommand on **every** git call, and never `--text` or `-a` | holds |
| T-B-8 | Missing base / missing head / shallow clone / empty diff / two merge bases (criss-cross fixture) | `git-failure` ×3, `empty-diff`, `ambiguous-merge-base` |
| T-B-9 | A path with a tab, and a path that is invalid UTF-8 (`os.fsencode` bytes name) | `unrepresentable-path` |
| T-B-10 | `base` = `--output=x` is rejected before git runs (CLI exit 2); `head` not 40-hex is exit 2 | holds |
| T-B-11 | R-A6 regression (codex CWE-345). Python file with two functions whose bodies are 7 or more identical lines. Branch A flips a line mid-body in the first function; branch B flips the same line in the second. Then `decide()` runs with A's authorize act and B's computed binding | the bindings differ; `decide` gives not authorized (`stale`) |
| T-B-12 | R-A6, not `-W`. Shell file with two identical top-level `if … fi` blocks (the §4.7 `gate.sh` fixture); flip one line in each | the bindings differ (the test asserts the raw `--function-context` ids are **equal**, so this fixture keeps proving `-W` is insufficient) |
| T-B-13 | R-A6 common case. Every hunk's 3-line pre-image is unique | the binding equals `patch-id --verbatim` of the `--unified=3` patch computed directly (rung 3, so T-B-2's ESC-3 behaviour is unchanged) |
| T-B-14 | R-A6 with ESC-3 under escalation. Ambiguous step (rung 10). (i) `main` edits the same file more than 10 lines from the hunk, then a clean merge. (ii) `main` edits within 4 to 10 lines of the hunk, then a clean merge | (i) equal; (ii) differs |
| T-B-15 | R-A6 ladder exhaustion. A file of 300 identical lines; flip line 120 in A and line 180 in B | both compute (whole-file rung), deterministic across two runs, A differs from B |
| T-B-16 | R-A6 edges: a new file, a deleted file, an empty old blob receiving content, an EOF hunk on a file with no trailing newline (`\ No newline` lines), a binary change, and a pure-addition hunk whose 3-line context occurs twice | each computes without error; the pure-addition case escalates (asserted through a `_run_git` spy seeing `--unified=10`) |
| T-B-17 | R-A6 fail-closed parser. Through the `_run_git` seam: a synthetic patch whose pre-image is absent from the stubbed old blob; a truncated hunk; an `index` line that is not 40-hex | `git-failure` ×3 |

**S1b additions (§10.4.6).** "Fake clock" means `monkeypatch.setattr(ha.time, "monotonic", lambda: clock[0])`, as in T-F-7.

| Id | Case | Expect |
|---|---|---|
| T-B-18 | Budget. A `_run_git` wrapper delegates to the real one and adds `BINDING_BUDGET_SECONDS / 2 + 1` to `clock[0]` after each call. Run on T-B-1's repo | `VerifierError("budget-exhausted")`, raised before the 3rd git call (the wrapper saw exactly 2 calls) |
| T-B-19 | The deadline is per call, not set at import: `clock[0] = 10 × BINDING_BUDGET_SECONDS` before the first call; two `compute_binding` calls with no clock advance | both succeed, with equal bindings |
| T-B-20 | Blob cache hoisted. Use T-B-11's ambiguous fixture (rung 3 is unanchored, rung 10 anchors). A spy wraps `_run_git` and records argv | at least 2 `diff` calls (rungs 3 and 10); each `cat-file blob <id>` argv occurs **exactly once** |
| T-B-21 | Every git call is budgeted (static). `ast`-walk `human_authorization.py` | the only `Call` nodes whose function is `_run_git` lie inside `_git_budgeted`. `compute_binding`'s first statement after its docstring assigns `deadline` from `time.monotonic()`. No module-level assignment calls `time.monotonic` |
| T-B-22 | Size cap. (i) `monkeypatch.setattr(ha, "BINDING_BYTES_MAX", 64)` on T-B-1's repo. (ii) T-B-11's fixture, with the cap set to `len(rung-3 patch) + 1` (measured in the test). (iii) Through the `_run_git` seam, calling `_anchored_patch(".", mb, head, deadline=math.inf)` directly: `diff` returns T-B-17's one-hunk synthetic patch `P`, and `cat-file blob` returns `len(P) + 50` bytes containing the pre-image once. The cap is `len(P) + 1` | `patch-too-large` ×3: (i) at rung 3; (ii) at rung 10, after rung 3 passed the cap; (iii) on the blob read (cumulative blob bytes) |
| T-B-23 | The default cap does not move T-B-13's common case | binding unchanged; no `patch-too-large` |

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
| T-F-7b | The deadline is per call, not set at import. Monkeypatch `time.monotonic` to return `T0 + 10 × FETCH_BUDGET_SECONDS` (as if the process had been alive long after import). Then call `fetch()` twice with the happy-path fake, advancing the clock by less than `FETCH_BUDGET_SECONDS` within each call | both calls succeed; neither raises `budget-exhausted` |
| T-F-8 | Page 10 full on the issue; and page 10 full on the PR | `pagination-bound` ×2 |
| T-F-9 | Page 2 is a dict, not a list | `payload-shape` |
| T-F-10 | A comment with a bad `created_at`, a non-int id, a missing `body`, `user.login` not a str, or a duplicate id across sources | `payload-shape` ×5 |
| T-F-11 | Repo metadata with no `default_branch` | `default-branch-unreadable` |
| T-F-12 | CODEOWNERS 404 / `encoding != base64` / invalid UTF-8 | `codeowners-unreadable` ×3 |
| T-F-13 | Default-branch `machine-accounts.env` 404 | `machine-accounts-unreadable` |
| T-F-14 | No partial decision: in every case T-F-3 to T-F-13, `decide` (spied) is never called | holds |

**S1b additions (§10.4.4, option G).** A second recording fake replaces `_run_gh_graphql`. Its key is `(number, after)`, and it returns the GraphQL response dict. The happy response for source `n` is `{"data":{"repository":{"issueOrPullRequest":{"__typename":"Issue","number":n,"timelineItems":{"filteredCount":0,"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]}}}}}`. Every T-F-1 to T-F-13 fake also answers this happy response, so those tests keep their meaning. **T-F-14 is extended to the fault cases T-F-17 to T-F-20.**

| Id | Case | Expect |
|---|---|---|
| T-F-15 | Happy path with `--pr`. One node `{"__typename":"CommentDeletedEvent","databaseId":901,"createdAt":"2026-10-20T12:00:00Z","deletedCommentAuthor":{"login":"ScottThurlow"}}` on the PR, `filteredCount 1`. Spy on `subprocess.run` for the real `_run_gh_graphql` argv | `Fetched.deletions == (Deletion(901, "2026-10-20T12:00:00Z", "ScottThurlow", pr),)`. The argv is exactly `["gh","api","graphql","-f","query="+DELETIONS_QUERY,"-f","owner=o","-f","name=r","-F","number=<n>"]`, with no `after` on page 1. `deletedCommentAuthor: null` gives `author_login None` |
| T-F-16 | Order: the recorded call sequence across both fakes | both graphql calls (issue, then PR) come **after** the last comment GET |
| T-F-17 | Transport faults on the graphql seam: rc=1 with `{"data":…,"errors":[…]}` on stdout; `TimeoutExpired`; `OSError`; invalid JSON | `api-error`, `timeout`, `api-error`, `payload-shape` |
| T-F-18 | Shape, one per row: rc=0 but an `errors` key present; `issueOrPullRequest: null`; `number` ≠ the requested number; `__typename` `"Discussion"`; a node with `__typename` other than `CommentDeletedEvent`; `databaseId` `true` / `0` / `"901"`; `createdAt` `"2026-10-20 12:00"`; `deletedCommentAuthor` `{"login": ""}` / `{"login": 5}` / `"x"`; `filteredCount 2` with one node collected; `hasNextPage true` with `endCursor null` / `"a b"`; one `databaseId` on both sources | `payload-shape` ×16 |
| T-F-19 | Pagination: page 1 has `hasNextPage true, endCursor "Y3Vy"`, and page 2 ends the list. Then: every page up to `DELETION_PAGE_BOUND` has `hasNextPage true` | the second call carries `"-f","after=Y3Vy"`, and the nodes from both pages are kept; then `pagination-bound` |
| T-F-20 | Budget: the fake clock passes `FETCH_BUDGET_SECONDS` after the last comment GET | `budget-exhausted`; the graphql fake is never called |
| T-F-21 | Static: `DELETIONS_QUERY.lstrip().startswith("query(")`; `"mutation"` does not occur in it (case-insensitive); exactly two functions in the module call `subprocess.run` with an argv starting `"gh"` (`_run_gh_get`, `_run_gh_graphql`); `_run_gh_get`'s argv is unchanged (T-F-1) | holds |

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
| T-CLI-18 | **S1b, R-S1-5 end to end.** The comment fake returns only a valid current authorize (t1). The graphql fake returns one `CommentDeletedEvent` by `ScottThurlow` at t1 + 2 h. The real `audit_log` writes to `tmp_path` | exit 1, `verdict "not-authorized"`, `covered []`, `act.decision "authorize"`; `refusals` is exactly one `{reason "deleted-later", detail "event:<id>"}`; exactly one `human-authorization-refused` event and **no** `human-authorization` event |
| T-CLI-19 | **S1b.** A `decide` spy | it receives `deletions=f.deletions` (identity) as a keyword |
| T-CLI-20 | **S1b, HQ-1.** The graphql fake raises `VerifierError("api-error")` while every other read succeeds and a valid act exists | exit 3, `verdict "undetermined"`, `covered []`, one api-failure event with `detail "api-error"` |

T-CLI-5 also covers `patch-too-large` (via a `compute_binding` fake raising it) and S1b's `budget-exhausted` from the binding phase.

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
| S1b: R-S1-5 closed (`deleted-later`), fail-closed deletion read (HQ-1), binding budget, blob cache, size cap | T-P-31 to T-P-41, T-F-15 to T-F-21, T-CLI-18 to T-CLI-20, T-B-18 to T-B-23 |
| `parse_codeowners_humans` existing cases unchanged; R-A7 tightening | `test_requester_trust.py` §3.4 (`TestParseCodeownersHumans`, `TestParseCodeownersHumansStrict`); `decide()` regression `test_inline_comment_owner_cannot_authorize` |

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

### 10.1 Architect rulings (round 1, 2026-10-22)

**Verdict: APPROVED WITH CHANGES.** The changes below were applied to this document by the architect. They are mechanical and need no further technical-design round. S1 may go to `coder`.

**R-A1 (ARCH-Q1, deletion resurrection): S1 ships without mitigation; R-S1-5 is accepted for the inert S1 only. It is NOT accepted for live use, and gates S2's merge.**
- *Why not mitigate in S1.* The only proposed mitigation (GraphQL `CommentDeletedEvent`) adds a second transport (POST) and a second fetch to the trust path, and it is unprobed: nobody has confirmed that a deletion of another user's issue comment by an App is reliably visible, or with which fields. Putting an unprobed read into the trust decision is worse than a stated residual in a module with no caller.
- *Why it is not harmless.* The resurrected act did name the exact current binding, so the content is something the human once approved. But for `C10:*` and `BF:*` items on a non-CRITICAL, non-protected step, the overseer may auto-merge (ceiling HIGH), so #757 is **not** a backstop there. The human's retraction would be silently lost. That is a user-observable failure mode on the hardest gate.
- *Binding instruction for S2.* S2's technical design must, before S2 merges, do one of:
  (a) probe REST `GET /repos/{o}/{r}/issues/{n}/timeline` (same GET transport, no `-f`) for a comment-deletion event naming the deleted comment's author and time. If it exists, add it to the fetch as fail-closed input and add refusal reason `deleted-later`: any deletion of a verified CODEOWNER's comment newer than the governing act makes the result unmet. This is a protected-file change to the verifier, ≤4 files, inside S2's or a dedicated S1b slice's budget; or
  (b) carry the human's explicit, own-account acceptance of R-S1-5 for live use.
  (a) is my recommended path. GraphQL is acceptable only if REST does not expose the event, and then only as a fail-closed read.
- **Human question (product-boundary checkpoint; blocks S2 merge, not S1 coding): HQ-1.** "If (a) proves impossible on the REST API, do you accept that a decline you post can be erased by a bot deleting it, letting your earlier authorize for the same exact content stand?"

**R-A2 (ARCH-Q4, exit-0-only versus per-item split): the per-item split is allowed, under exact conditions.** This resolves the AD-2/AD-6 tension. AD-2's "only 0 clears an item" is read as "only 0 authorizes the **whole request**". A consumer that asks for several items in one call may clear an individual item **iff all** of the following hold:
1. the process exit status (not the JSON's `exit_code` field) is 0 or 1;
2. stdout parses as the §4.9 JSON object, `schema == "hos-human-authorization/v1"`, and its `exit_code` equals the process exit status;
3. `error` is `null`;
4. the item is in `covered`.

Any other state (exit 2, 3, 4, any other status, unparseable or mismatched JSON) clears **no** item. `pr_readiness` REQ-W-07 asks for `C7` alone and uses exit 0 only. The overseer's re-verify never splits: any non-zero exit is HUMAN_REQUIRED. S2's design cites this ruling. S1 already guarantees what it relies on (§2 rule 6, §4.9 exit 4). Classification: clarifying; no product consequence, because any unmet item still keeps the step from PROCEED. I do not amend the human-approved ADR text for this; S2's design records it as an ADR-2101 erratum in `DECISIONS.md`.

**R-A3 (binding environment pinning, a defect found in review): pin the attribute source.** §4.7's environment strip and config pins are correct, and the `--text` prohibition and `--full-index` reasoning are right. But a **working-tree** `.gitattributes` with `-diff`/`binary` changes the id (reproduced; §4.7). The worker and overseer compute from different checkouts, so a step that edits `.gitattributes` would get a permanent, unclearable `stale` at the overseer. Fixed: `--attr-source=<empty tree>` on every git call, test T-B-6a, T-B-7 extended, minimum git version declared (git-failure, closed, on older git). R-S1-2 (`info/attributes`) stands, since it is per-clone and only over-refuses.

**R-A4 (requester_trust conformance-test change): approved, with the assertions replaced.** Widening `test_no_second_codeowners_parser_in_framework` by one delegating reader is correct and the #1540 sign-off on that test stands. But the round-1 `"read_text" not in ha_text` ban contradicts this TD's own `--findings-file`, `--verdict-file` and §4.11 reads, and `"codeowners_humans(repo_root"` is trivially evaded by a keyword argument. Replaced in §3.4. T-CLI-9 is the behavioural guard and is mandatory.

**R-A5 (render text):** §4.4 `render_request` item 2 now says to copy only the boxed text, whose first line is the `/hos` line. Otherwise a pasted whole block is silently ignored under AD-1, which REQ-8's "a human's newest word must never be silently skipped" intends to prevent.

**ARCH-Q2 (any later edit by the CODEOWNER voids the act): the technical call is approved as drafted.** The narrower rule ("only edited candidates poison") reopens two resurrection attacks; the only other narrowing ("only edits by someone other than the author poison") needs GraphQL `userContentEdits.editor`, a second transport. The fail-closed rule stands for S1. It is a **user-visible** over-refusal beyond the ADR's literal "edited act is refused", so under the product-boundary checkpoint it goes to pm-agent and the human before it is live:
- **Human question HQ-2 (blocks S2 merge, not S1 coding):** "After you authorize a step, editing any later comment of yours on that issue or PR voids the authorization until you post a fresh one. Accept that, or require the editor-identity check (a GraphQL read) so that only edits by someone else void it?"
- The S1 PR's "Human Review Required" section discloses it, and `render_request` line 7 tells the human.

**ARCH-Q3 (closed-set additions): approved.** `superseded` is required for AD-10's one-event-per-candidate to hold. Every added field is additive, and none carries body text. `ParseError.key` is restricted to the four allowed keys, which keeps `duplicate-key:<k>` privacy-clean; the coder pins that `unknown-key` is checked before `duplicate-key`.

**ARCH-Q5 (extra extractions `parse_env_text`, `bot_baseline_from_env_text`): approved.** I re-read `requester_trust.py:242-255` and `:301-322`. Both are pure moves, and `load_trusted_apps` (also a `_parse_env_file` caller) is unaffected. A second `.env` parser would be a drift site on a security input. AD-2's "public functions of `requester_trust`" covers them; no ADR change.

**ARCH-Q6 (grammar refinements): approved.** Each one moves a near-miss from "silently ignored" to "malformed", or accepts the fenced form AD-9 itself presents. None widens what is accepted beyond the canonical form.

**ARCH-Q7 (no GraphQL `lastEditedAt` alternative; R-S1-1 accepted): approved.** The probe evidence (hidden comments have `lastEditedAt == null`) shows the alternative would accept a minimized comment. AD-4 permitted, never required, it. R-S1-1's one-second window is negligible against an actor that is our own App.

**Scope and import checks (asked by the worker): pass.**
- Files: 11, the ADR's S1 row, within the ≤15 cap. `regen_all.sh` changes only `SCRIPTS-INDEX.md` (CODEOWNERS covers `/scripts/framework/` by directory). The §4.11 record is runtime state under `.claudetmp/`, not a repo file.
- Imports: stdlib, `require_human_approval` (stdlib-only imports, re-checked) and `requester_trust` (stdlib + `require_human_approval`). Nothing from `scripts/automation/**` or `scripts/oversight/**`, directly or transitively. `audit_log` is reached only by subprocess (AF-3). T-CLI-16 pins it.

**S2 prerequisites recorded here so they are not lost (none blocks S1):**
- **S2-PRE-1:** R-A1 resolved (mitigation (a) built, or HQ-1 answered).
- **S2-PRE-2:** HQ-2 answered.
- **S2-PRE-3 (product-boundary: consumer operational obligation).** Consumers do not receive `scripts/framework/machine-accounts.env` (not in `framework_consumer_files.txt`; re-checked), so every consumer `verify` exits 3 and the human gate is unsatisfiable there. S2 must decide with pm-agent and the human how a consumer provisions and commits that file to its default branch, and add the minimum git version (R-A3) to the consumer prerequisites. Fail-closed is correct; an unsatisfiable gate in every consumer is a product consequence that needs clearance.
- **S2-PRE-4:** consumers take `--repo` from protected configuration, never from agent prose. A caller-chosen repo selects whose CODEOWNERS and comments are read. The overseer's own-clone re-verify (AF-5) remains the anchor.

### 10.2 S1 implementation amendments (2026-10-22)

The S1 reviewers (security, privacy, reliability) found the gaps below in the coded verifier; commits `2b5ae3517` and `05cf44cb1` closed them and this TD now records them in §4.7, §4.8, §4.9, §4.10 and §6. Classification: **additive / fail-closed refinements**. None widens what is accepted or changes the exit contract; each either removes an output channel or turns a previously unspecified state into exit 3.

| Change | Source |
|---|---|
| Refusal writes stop after the first failure; skipped writes count as failed (record not updated); one WARN; acceptance always attempted, failure still exit 4 with `covered = []` (§4.10) | reliability review (avoids N × 30 s stalls on a degraded audit writer) |
| Any unexpected exception in fetch/decide is `api-error`, exit 3; `main()` last-resort catch returns 3 (§4.8, §4.9, §6) | S1 review (`05cf44cb1`) |
| `gh` stderr is never echoed; the diagnostic is `gh api exit=<rc>` plus an optional `HTTP <ddd>` (§4.8) | privacy review |
| Contents reads use `ref=refs/heads/<branch>` (§4.8) | security review (CWE-345, tag shadowing) |
| `gh` and `git` run with `stdin=DEVNULL`; `gh` with `GH_PROMPT_DISABLED=1` (§4.7, §4.8) | S1 review (`05cf44cb1`) |
| CLI and API input regexes use `fullmatch` (§4.9) | S1 review (`2b5ae3517`) |
| Every git call passes `--no-replace-objects` (§4.7); regression test installs `git replace <unauthorized> <authorized>` and asserts the binding still reflects the real objects | second review (codex), CWE-345 |
| `is_representable_path` also asserts `canonicalize_path(p) == p`; `render_request` scrubs URLs and the parse-error fields with the same AD-9 forbidden-string replacement as finding text (§4.4, §4.5) | second review (agy) |

**S2 precondition added:**
- **S2-PRE-5: SUPERSEDED by R-A7 (§10.3), which fixes it in S1.** Retained for history: `requester_trust.parse_codeowners_humans` (§3.1, moved verbatim) treats every whitespace-separated token after the pattern as an owner, so inline `#`-comment words and escaped-space path fragments are accepted as human logins. Before S2 makes the verifier the sole human gate, it must accept only `@`-prefixed tokens matching the GitHub login grammar and stop at the first unescaped `#`. S1 is inert, so this does not block S1; it blocks S2's merge.

### 10.3 Architect ruling R-A6 (2026-10-22): the binding must be position-sound. S1 carries the fix.

**Finding** (second review, codex, CWE-345, high; `.claudetmp/second-review/step2101-s1-20261022T215237.md`). `git patch-id --verbatim` hashes hunk text but not hunk positions. If one file has two locations with the same context window, the same edit at either location gives the same binding. A human's authorize act for a harmless edit (the preview function) then also covers the same text edit in a sensitive location (the production function). `reviewed_files` overlap does not help, because the path is the same.

**Reproduced by the architect** (real git 2.53.0, the exact §4.7 argv, scratch repo under `$TMPDIR`; table rows in §4.7). The hunks collide at `--unified=3` and `--unified=5`. Paths **are** hashed: the same edit in a different file gives a different id, so the defect is within one file only. `--function-context` separates the Python fixture, but **not** a shell fixture with identical top-level `if` blocks. Git's default funcname rule is `^[A-Za-z_$]`, and the verifier pins `--attr-source` to the empty tree, so no language driver applies. In shell, Markdown and YAML, where agent definitions and other governance surfaces live, the "function" is often one or two lines. `-W` is therefore rejected as the fix.

**Ruling.** This is option (a), inside AD-5 and ESC-3's delegation. S1 carries it now.
- The binding stays `patch:` + `git patch-id --verbatim` of the step's own diff, with every pin unchanged. Only the context width is chosen by rule: the context ladder plus pre-image uniqueness in §4.7 steps 5 and 5a.
- The common case, where every hunk's 3-line pre-image is unique, gives a binding byte-identical to today's (T-B-13).
- A hunk whose window is ambiguous gets the smallest rung of `(3, 10, 30, 100, whole-file)` that makes every pre-image unique in its old blob. A unique pre-image fixes the hunk's position from the text alone, so equal bindings at one merge base mean equal changes. The one residual is R-S1-6 (§6).

**Why not codex's blob-id manifest.** A manifest of (path, old blob, new blob, mode) voids the act whenever `main` touches any file the step changes. That is the stricter behaviour the human declined in ESC-3, so adopting it would be a human decision, not mine. The ladder is complete for the reproduced attack class and keeps ESC-3.

**Effect on ESC-3.** The human-approved AD-5 promise ("a merge from `main` that leaves the step's own changes identical keeps the binding"; R-2 "a change in `main` to context lines adjacent to the step's hunks voids it") still holds as worded. AD-5 never fixed the context width, and the ADR definition string has no `-U`.
- Only steps that hit an ambiguous window see a change. For them, "adjacent" grows from 3 lines to the escalated rung (10/30/100/whole file). A `main` edit inside that wider window voids the act, which is closed: the human posts a fresh act.
- This is a fail-closed narrowing of an over-refusal the human already accepted (R-2). It does not change what an act authorizes or who may authorize. Under the product-boundary checkpoint I therefore classify it as **disclosure, not a gate**. The S1 PR's "Human Review Required" section states it. No human question.

**Coder obligations (S1, same files).**
- `compute_binding` implements §4.7 steps 5 and 5a.
- Add tests T-B-11 to T-B-17 in `test_human_authorization_binding.py`. T-B-11 must go through `decide()`.
- T-B-7's spy assertion stays: the first diff call carries `--unified=3`, and every diff call carries every other pin.
- The module docstring names the ladder and R-S1-6.
- No new refusal reason, exit code, JSON field or binding format. The rung is not exposed, so the AD-10 closed set is unchanged.
- Cost: at most 5 diff calls, one `patch-id`, and one `cat-file` per changed text file per call. All are under the existing `GIT_TIMEOUT_SECONDS`, and a timeout is `git-failure`.

**ADR text.** Unchanged. The ladder lies within AD-5's "pinned options". As with R-A2, S2's design records an ADR-2101 erratum in `DECISIONS.md` that names R-A6 and R-S1-6.

**Reviewer re-review.** `security-reviewer` and `code-reviewer` re-review the `compute_binding` change, and `unit-test` covers T-B-11 to T-B-17. The codex second review re-runs scoped to the fix commit. See §11 for the affected sign-offs.

### 10.3 (cont.) Architect ruling R-A7 (2026-10-22): tighten the shared CODEOWNERS parser in S1. This replaces S2-PRE-5.

**Finding.** The final full-range second review (codex, high, CWE-863) and the S1 `security-reviewer` (SHOULD_FIX, previously deferred as S2-PRE-5) found the same defect. `parse_codeowners_humans` accepts every whitespace token after the path as an owner. It requires no `@`, does not cut at an inline `#`, and does not honour escaped spaces in the path. So `* @maintainer # alice handles triage` makes `alice`, `handles` and `triage` human authorizers. In the same way, `docs/My\ File.md @x` makes `file.md` one.

**Ruling: (a), fix in S1. The precise rule is §3.1's R-A7 block; the tests are in §3.4.** Deferring would be wrong for two reasons:
- The parser is **shared and live today**. `requester_trust.load_trusted_set` (`:421`), `select_work_candidates.py:342` and `probe.py` (the needs-ai actor check, `:408`) all use it. The over-acceptance is a present defect in running trust decisions, not only in the inert verifier.
- The fix is small and pure, it only ever reduces the set, and S1 already owns the function (§3.1).

**Behaviour change (deliberate, fail-closed).** `codeowners_humans` now returns a subset of what it returned before, for every input. Every caller either intersects actors with the set or treats an empty set as a configuration failure: the selector's `codeowners-no-individual-human`, the verifier's `codeowners-empty`, and probe's skip when there is no verified actor. No caller treats a smaller set as more permissive (all four call sites re-read). A smaller set can therefore only refuse more, never authorize more.

**Real-repo check.** `.github/CODEOWNERS` has 24 owner tokens, all `@ScottThurlow`. Its `#` characters all sit on full-line comments, and no path has an escaped space. `gen_codeowners.sh` always emits `@`-prefixed handles (its `OWNER` is forced to start with `@`). The parsed set is unchanged (`{"scottthurlow"}`), and §3.4 pins this. A consumer CODEOWNERS loses only tokens that were never valid GitHub user owners:
- inline-comment words and path fragments, which were the bug;
- bare words, which GitHub itself rejects as owners;
- emails, which never equalled a login and so never matched an actor.

So the change has **no product consequence** to route. It is a security fix that the PR discloses.

**Coder obligations.**
- Implement §3.1's R-A7 block in `requester_trust.py`, including the docstring update.
- Add the §3.4 strict tests and the `decide()` regression.
- Update the remediation string of the selector's `codeowners-no-individual-human` failure in `select_work_candidates.py`. It says the file "lists only team handles", which is now also reached by a file with only bare names or emails. The new text: "this file names no individual `@user` handle (team handles, emails and bare names do not confer authorization authority). Add at least one individual user handle."
  - The reason code is unchanged.
  - This adds one file to S1 (12, within the ≤15 cap).
- No other caller changes.

**Re-review.** `security-reviewer` re-reviews `parse_codeowners_humans` and the selector string. `code-reviewer` and `unit-test` review the new tests. The scoped second review re-runs.

**Decision (#2151 re-adoption, code-review MUST_FIX-1): the merge path adopts R-A7.** `merge_authority._codeowners_humans_from_text` (`scripts/automation/lib/merge_authority.py`) no longer keeps its own text parser; it delegates to `requester_trust.parse_codeowners_humans`. The strict set is **not** a subset of the old one: a mid-token `#` (`docs/a#b.md @alice`) or an escaped `\#` (`\#notes.md @bob`) gives the strict parser owners (`alice`, `bob`) that the old truncate-at-`#` parser dropped. The merge path stays safe by a different argument. The guard is only a membership test on `resolved.login`, and the oversight resolver (`scripts/oversight/codeowners.py`) cuts at the first `#`, so any login it can pick was already in the old set. Guard-pass under the new parser therefore implies guard-pass under the old one, and the extra owners can never be the picked login (T-CO-1c pins this). The net merge-path effect is monotonic fail-closed. **Rejected alternative:** filtering the resolver with `OWNER_LOGIN_RE`. `resolved.login` is authority-bearing (its review acts are counted), so a filtered resolver would silently skip a malformed token and fall through to the next owner or the default human, shifting who holds approval authority. Escalating through `CodeownersDriftError` is the correct fail-closed outcome and keeps one parser. The resolver (`resolve_reviewer_from_text`) is unchanged and still resolves a bare word, `@a#x`, an invalid handle such as `@-bad`, or a handle over 39 characters as the reviewer. `check_resolution_consistent` then raises `CodeownersDriftError`, so the merge path **deliberately accepts extra drift escalations on malformed owner tokens** rather than authorizing on them. `tests/automation/test_route_pr.py` T-CO-1 pins the strict sets as literals and T-CO-1b pins these divergences.

**Amendment R-A7a (2026-11-18, #2151 second review, agy, high, logic-error).** §3.1 rule 3 as first written stopped only at an owner token that *starts* with `#`. A `#` attached to an owner token did not stop the loop: in `* @alice# see @bob` or `* @org/team# ask @bob`, the `#` token failed the grammar and was skipped, and then `@bob`, which is comment text, was accepted as a human CODEOWNER. The parser is live (selector, trust set, needs-ai probe, `approval_merge`, `merge_authority` delegation), so this widened authority on live paths. It contradicted the merge-path resolver (`scripts/oversight/codeowners.py:68`, which the argument above relies on), the O19 reader (`scripts/automation/lib/codeowners.py:57`), both of which cut at the first `#` anywhere on the line, and the existing pin `test_inline_comments_are_stripped` ("'#' starts a comment anywhere on a line"). **Fix:** rule 3 now stops at the first owner token that *contains* a `#`, and that token is not accepted. Classification: **clarifying, fail-closed.** It can only drop owners, never add one. For owner tokens, the strict set is now always a subset of what a first-`#` cut would accept, so the merge-path argument above holds unchanged (the only remaining divergence is in the path token: `docs/a#b.md`, `\#notes.md`, deferred to S2-PRE-8). **Unchanged:** the path-token rules (`_codeowners_rest`, escaped `\ ` and `\#`), and S2-PRE-8. Every existing case in `TestCodeownersHumans`, `TestParseCodeownersHumansStrict`, T-CO-1 and T-CO-1b keeps its expected set (`@a#x` and `#@mallory` already gave nothing). **Coder obligations:** change the loop's stop test from "starts with `#`" to "contains `#`"; update the `parse_codeowners_humans` docstring to match ("the first owner token containing `#` starts an inline comment and ends the owner list; that token is not an owner"); add the three R-A7a rows in §3.4; add `test_attached_hash_comment_owner_cannot_authorize` in `test_human_authorization_predicate.py`. That test parses `* @maintainer @carol# see @alice` (set `{"maintainer"}`) and runs `decide()`. An otherwise-valid, unedited, current-binding `authorize` act by `alice` (not a bot) is refused `not-codeowner`, and so is the same act by `carol`. The same act by `maintainer` is authorized. (Do not use a line whose set is empty: the CLI path raises `codeowners-empty` before `decide`, §4.9 step 5.) No other file changes.

### 10.4 Slice S1b (#2151): the `deleted-later` refusal and the binding wall-time budget

**Status:** APPROVED WITH CHANGES by the architect, 2026-10-30. **ARCH-Q-S1b is ruled G (R-A8, §10.4.9).** The amendments R-A8 makes are applied in place below and marked "(R-A8)". S1b may go to `coder` on this text. Where §10.4.9 and an earlier subsection disagree, §10.4.9 governs.

**Inputs.**
- #2151.
- §10.1 R-A1, option (a).
- **HQ-1**, answered by `ScottThurlow` on his own account on 2026-10-22: "refuse fail-closed (deleted-later) if deletion can't be detected."
- The S1 `reliability-reviewer`'s SHOULD_FIX: `compute_binding` has no wall-time bound across the R-A6 ladder.

**Change class: additive.** Every change either refuses in more cases or fails closed in more states. None widens what is accepted. The exit contract, the JSON key set and the binding format are unchanged. Two closed sets each gain one member: `REFUSAL_REASONS` gains `deleted-later`, and `ERROR_CODES` gains `patch-too-large`.

#### 10.4.1 Probe result (2026-10-30, read-only)

The full record is in `research/findings/api-field-shape-verification.md`, in the section "2026-10-30 probe".

- **REST.** `GET /issues/{n}/timeline` (and `/issues/{n}/events`) carries `event: "comment_deleted"`. Its key set is `actor`, `commit_id`, `commit_url`, `created_at`, `event`, `id`, `node_id`, `performed_via_github_app` and `url`. `actor` is the **deleter**, and `created_at` is the **deletion** time. No field gives the deleted comment's author, id or creation time.
- **GraphQL.** `CommentDeletedEvent` has `databaseId` (equal to the REST `id`), `createdAt` (equal to the REST `created_at`), `actor` (the deleter) and `deletedCommentAuthor`, which was `null` in 17 of 58 events. It does not give the deleted comment's creation time either.
- **REST listings are incomplete.** The sample was 36 public threads holding 58 GraphQL events. The REST listings gave 47 of the 58. The 11 missing events sit in 2 PR threads. Every one of them is retrievable from REST by id, so REST stores them but does not list them, and nothing marks the gap. The cause is unknown.
- **The attack shape is recorded.** A GitHub App deleted a `User` account's comment in 5 of 5 cases, and both transports recorded it (REST `actor.type == "Bot"`).
- **Self-deletion was not observed.** In the 41 events with a known author, the deleter was never the author.
- **This repo** has had no comment deletions to date.

#### 10.4.2 ARCH-Q-S1b: which transport carries the deletion read (ruled G by R-A8, §10.4.9)

| | **G: GraphQL query (recommended)** | **R: REST timeline GET** |
|---|---|---|
| Transport | `gh api graphql` with one fixed read-only query (a POST); a 4th seam | `gh api` GET; the existing seam |
| Deleted comment's author | yes (`deletedCommentAuthor`; `null` means unknown) | no |
| Observed completeness | 58/58 (GraphQL was the discovery source, so this is not a measurement of its own misses; R-S1b-2). Pagination integrity is checked against `filteredCount`, a **same-source** count, not an independent one (R-A8) | 47/58; misses carry no signal |
| Rule (§10.4.5) | a deletion counts if its author is a CODEOWNER or unknown, and its time is ≥ the governing act's `created_at` | every deletion counts if its time is ≥ the governing act's `created_at` |
| Residual | R-S1b-1, R-S1b-2 | R-S1b-1, R-S1b-2, **R-S1b-3** (silent misses) |

**Recommendation: G.**
1. **R fails open, silently, on data we have observed.** An unlisted deletion leaves the older authorize governing, and nothing in the response shows that anything was missed. HQ-1 says to refuse when a deletion cannot be detected. Under R the verifier cannot know it missed one, so it cannot refuse. G checks the nodes it collects against `filteredCount` and fails closed on any mismatch. *(R-A8 correction: that check proves the pages were read whole and unchanged; it does not prove the server's own count is complete. That residual is R-S1b-2, closed by S2-PRE-6.)*
2. **G over-refuses less.** Only deletions of CODEOWNER-authored or unknown-author comments count. R counts every deletion of anyone's comment.
3. **The transport risk is contained.** G adds a fixed query text: no mutation, no caller-supplied query, and only validated variables. It keeps the same `gh` binary, authentication, timeout, return-code-before-parse rule and no-stderr-echo rule as `_run_gh_get`. T-F-21 pins all of this statically.

**The case for R.** R-A1 preferred a single GET transport, and this repo has had no deletions. If the architect rules R, R-S1b-3 is the HQ-1 situation, narrowed but not closed, so it **goes back to the human** as an own-account acceptance before S2 merges. G needs no further human answer.

A union of both transports adds nothing observed: every REST-listed event was also in GraphQL (47 of 47). It is not recommended.

#### 10.4.3 Constants and types (these extend §4.2 and §4.3)

```
REFUSAL_REASONS   |= {"deleted-later"}
ERROR_CODES       |= {"patch-too-large"}
DELETION_PAGE_BOUND    = 10                  # per source, 100 per page: 1,000 events. Not a flag.
CURSOR_RE              = re.compile(r"^[A-Za-z0-9+/=_-]{1,256}$")
BINDING_BUDGET_SECONDS = 120                 # whole compute_binding call; checked before each git call
BINDING_BYTES_MAX      = 16 * 1024 * 1024    # per ladder patch, and cumulative old-blob bytes per call

Deletion: event_id: int; deleted_at: str (TS_RE); author_login: str | None; issue_number: int
Fetched:  default_branch; codeowners_text; machine_env_text; comments; deletions: tuple[Deletion, ...]
          # appended last, no default (only fetch() constructs Fetched)
```

`DELETIONS_QUERY` (option G) is exactly the following text. It was run live on 2026-10-30 against an Issue (HOS #2101) and a PR (DefinitelyTyped #74968):

```
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue {
        number
        timelineItems(itemTypes: [COMMENT_DELETED_EVENT], first: 100, after: $after) {
          filteredCount
          pageInfo { hasNextPage endCursor }
          nodes { __typename ... on CommentDeletedEvent { databaseId createdAt deletedCommentAuthor { login } } }
        }
      }
      ... on PullRequest {
        number
        timelineItems(itemTypes: [COMMENT_DELETED_EVENT], first: 100, after: $after) {
          filteredCount
          pageInfo { hasNextPage endCursor }
          nodes { __typename ... on CommentDeletedEvent { databaseId createdAt deletedCommentAuthor { login } } }
        }
      }
    }
  }
}
```

Use `filteredCount`, never `totalCount`: `totalCount` ignores `itemTypes` (probe).

#### 10.4.4 Fetch: read 6 (option G)

**The seam: `_run_gh_graphql(owner: str, name: str, number: int, after: str | None) -> Any`.**
- **argv:** `["gh", "api", "graphql", "-f", f"query={DELETIONS_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={number}"]`, plus `["-f", f"after={after}"]` iff `after is not None`.
  - Every string goes through `-f`, which passes a raw string. `-F` would read a value starting with `@` as a file and convert types.
  - `number` is the only `-F` value. It is already `NUM_RE`-valid.
  - The argv never contains `--paginate`, `--input`, `--method` or `-X`.
- **Everything else matches `_run_gh_get` (§4.8, §10.2):**
  - `timeout=GH_TIMEOUT_SECONDS`, `stdin=DEVNULL`, and `GH_PROMPT_DISABLED=1`.
  - Failures map as they do there: `TimeoutExpired` gives `timeout`, `UnicodeDecodeError` gives `payload-shape`, and `OSError` gives `api-error`.
  - The return code is checked before any parse. A GraphQL error makes `gh` exit 1 with JSON on stdout (probed), so that is `api-error`.
  - The only stderr diagnostic is `gh api exit=<rc>`, plus `HTTP <ddd>` when present.
  - Invalid JSON gives `payload-shape`.
- `owner, name = repo.split("/", 1)`. `repo` has already passed `REPO_RE`.

**Read 6** runs after read 5. It covers `number` in `(issue,)`, or in `(issue, pr)`, in that order:
```
for number in sources:
    after, collected, fc0 = None, [], None
    for page in range(1, DELETION_PAGE_BOUND + 1):
        check_deadline()                       # same fetch() deadline as the GETs → budget-exhausted
        fc, has_next, cursor, nodes = _deletion_page(_run_gh_graphql(owner, name, number, after), number)
        if fc0 is None: fc0 = fc
        elif fc != fc0: raise payload-shape
        collected += nodes
        if not has_next: break
        after = cursor
    else: raise pagination-bound
    if len(collected) != fc0: raise payload-shape   # completeness check
```

`check_deadline()` is the existing `get` closure's deadline test, factored out so that both seams use it.

**`_deletion_page(resp, number)`** raises `payload-shape` on any violation of the rules below.
- **Envelope.**
  - `resp` is a dict, and `"errors" not in resp`.
  - `resp["data"]["repository"]["issueOrPullRequest"]` is reached through dicts at every level, and the last one is a dict too.
  - Its `__typename` is in `{"Issue", "PullRequest"}`, and its `number` is an int, not a bool, equal to `number`.
- **Connection.**
  - `timelineItems` is a dict.
  - `filteredCount` is an int ≥ 0, not a bool.
  - `pageInfo` is a dict whose `hasNextPage` is a bool, and whose `endCursor` is `None` or a str. When `hasNextPage` is true, `endCursor` must be a str that fullmatches `CURSOR_RE`.
  - `nodes` is a list.
- **Each node.**
  - It is a dict, with `__typename == "CommentDeletedEvent"`.
  - `databaseId` is an int > 0, not a bool.
  - `createdAt` is a str that fullmatches `TS_RE`.
  - `deletedCommentAuthor` is `None`, which gives `author_login = None`, or a dict whose `login` is a non-empty str, which gives `author_login = login`. Anything else is `payload-shape`.
  - The node becomes `Deletion(databaseId, createdAt, author_login, number)`.
- **Uniqueness.** A `databaseId` seen twice, on either source, is `payload-shape`.

**Order (load-bearing).** Deletions are read **after** every comment read. A comment missing from the comment read was deleted before the deletion read began, so its event is in the deletion read. The reverse order would leave a window: a deletion landing between the two reads would be invisible in both. A deletion after read 6 is not seen, just as any later act is not seen; the overseer re-verifies (AF-5).

**Failure.** Every failure here is a `VerifierError`, which gives exit 3 with `covered = []` and one api-failure event. The §4.8 "unexpected exception" mapping also covers this read. **This is HQ-1 as built:** the verifier never decides without a complete, validated deletion read of every source.

**Cost.** One extra call per source in the common case, and at most `2 × 10` more. The §4.8 maximum becomes 43 calls.

**Tests that run the real `fetch()`** (all of §7.4, and every in-process §7.5 test) install a `_run_gh_graphql` fake. By default it gives the empty happy response from §7.4. No test may reach the real seam; T-CLI-1 exits 2 before any read.

#### 10.4.5 `decide`: the `deleted-later` refusal

**Signature.** `decide(comments, codeowners, bots, step, binding, required_items, diff_files, *, deletions) -> Verdict`.
- `deletions` is keyword-only, with **no default**. A caller that forgets it raises `TypeError`, which the CLI maps to exit 3 (§4.9 last-resort), rather than silently skipping the check.
- New precondition: every element is a `Deletion`; otherwise `ValueError`.
- The CLI passes `deletions=f.deletions`.
- The test helpers `_decide` and the two `decide(` calls in `test_human_authorization_binding.py` pass `deletions=()`.

**Definition.**
```
qualifies(d, g) = (d.author_login is None or d.author_login.lower() in codeowners) \
                  and d.deleted_at >= g.created_at          # str compare; both TS_RE
```
The author test deliberately omits the bot exclusion. A login that is both in `BOT_ACCOUNTS` and in `codeowners` still counts, so the check errs toward refusing.

**Placement.** The check goes only in the last branch of §4.6, where the governing participant is a current authorize with a non-empty overlap. It runs after the overlap is computed and before `Accepted` is built:
```
else:                                           # overlap non-empty
    gov = G(c, "authorize")
    hits = sorted((d for d in deletions if qualifies(d, c)), key=lambda d: (d.deleted_at, d.event_id))
    if hits:
        refusals.append(R(c, "deleted-later", f"event:{hits[0].event_id}"))
        return Verdict(False, (), required_items, gov, None, sorted(refusals))
    accepted = …                                # unchanged
```
Every other governing outcome (`edited`, `malformed-latest`, `declined`, `stale`, `no-overlap`, or no participant) is already unmet. Keeping their reasons preserves AD-10's one event per candidate (T-P-41) and every existing T-P expectation. The result is exit 1 (decided on complete data). JSON `act.decision` is `"authorize"`, as it is for `stale`.

**Why the rule cannot miss a deleted newer comment.** Neither transport gives the deleted comment's creation time (§10.4.1).
- A comment deleted at time `d` was created at or before `d`.
- If `d < g.created_at`, the deleted comment was created strictly before the governing act, so it was never a newer participant under §4.6's `(created_at, id)` order.
- So every deletion that could have removed a newer participant has `d ≥ g.created_at`. The `≥` covers a same-second tie, which the id tiebreak could otherwise order either way.
- Every such deletion is caught when its author is a CODEOWNER or unknown. A comment by a non-CODEOWNER or a bot is never a participant (§4.6), so deleting it can resurrect nothing.

**Over-refusal (stated).** Each of the following voids the act until the human posts a fresh one (T-P-38):
- someone other than the author (R-S1b-1) deletes a CODEOWNER's comment that is **older** than the act, after the act;
- an unknown-author (ghost-account) comment is deleted after the act. Such authors were 17 of 58 observed events, typically spam cleanup;
- under option R, any comment at all is deleted after the act.

This repo has had no deletions to date.

**Detail and privacy.** The detail is `event:<databaseId>`: a public GitHub event id, never body text, in the same class as comment ids. The §4.11 fingerprint picks it up through the refusal detail.

**What HQ-1 means for the verdict.** Deletions are detectable (§10.4.1), so the verifier does not refuse every act. If the deletion events of any source cannot be read or validated completely, the verdict is exit 3 `undetermined`, `covered = []` (T-CLI-20). It is never a decision made without them.

**Note for S3 (no S1b change).** The `render_request` text should tell the human that if anyone else deletes one of their comments here after they authorize, the authorization is void until they post a fresh one. S3 owns that wording. T-PR-9 is unchanged.

#### 10.4.6 Binding: budget, blob cache, size cap

1. **`_git_budgeted(repo_root, args, deadline: float, *, stdin: bytes | None = None) -> bytes`.** If `time.monotonic() > deadline`, it raises `VerifierError("budget-exhausted", "binding budget exceeded")`. Otherwise it returns `_run_git(repo_root, args, stdin=stdin)`. `_run_git` is looked up as a module global, so tests that monkeypatch `_run_git` still intercept every call. `_git_budgeted` is the **only** caller of `_run_git` (T-B-21).
2. **`compute_binding`.**
   - Its first statement after the docstring is `deadline = time.monotonic() + BINDING_BUDGET_SECONDS`. It is never set at import and never shared between calls. The argument checks follow; they are pure.
   - Its git calls all go through `_git_budgeted(..., deadline)`: `rev-parse`, `cat-file -e`, `merge-base`, the ladder (via `_anchored_patch`), `patch-id` and the `--name-only` diff.
3. **`_anchored_patch(repo_root, merge_base, head, *, deadline: float) -> bytes`.**
   - Before the rung loop it creates `blobs: dict[str, bytes] = {}`, **once** (the hoist). A rung that fails anchoring therefore never re-reads a blob.
   - For each rung, in this order:
     1. `patch = _git_budgeted(repo_root, _diff_argv(...), deadline)`;
     2. `patch == b""` gives `empty-diff` (unchanged);
     3. `len(patch) > BINDING_BYTES_MAX` gives `VerifierError("patch-too-large", "ladder patch exceeds size cap")`;
     4. if `_hunks_anchored(repo_root, patch, blobs=blobs, deadline=deadline)`, return `patch`.
4. **`_hunks_anchored(repo_root, patch, *, blobs: dict[str, bytes] | None = None, deadline: float | None = None) -> bool`.**
   - It uses `blobs` as its cache, or a fresh dict when it is `None`. The zero id's `b""` entry is cached too.
   - Each read is `_git_budgeted(repo_root, ["cat-file", "blob", old_id], deadline if deadline is not None else float("inf"))`.
   - After inserting each newly read blob, if `sum(len(b) for b in blobs.values()) > BINDING_BYTES_MAX`, it raises `VerifierError("patch-too-large", "old blobs exceed size cap")`. The total is cumulative across rungs, because the cache is shared.
   - The positional form `_hunks_anchored(".", patch)` that T-B-16 and T-B-17 use keeps working. No import is added (§4.1 stays exhaustive).
5. **Cap scope.**
   - The cap applies to every ladder rung, not only the whole-file rung, and to the cumulative old-blob bytes.
   - It does not apply to the `--name-only` output, which is bounded by the paths, or to the `patch-id` output.
   - The `patch-id` stdin is a ladder patch, so it is already within the cap.
6. **Call-time reads.** `BINDING_BUDGET_SECONDS` and `BINDING_BYTES_MAX` are read at call time as module attributes, never bound as default arguments, so tests can monkeypatch them.

**Why 120 s.**
- **Measured.** A real `binding` run on this branch (14 files, +4,639 lines; a 218 KiB `-U3` patch, 436 KiB at whole-file context) took **0.08 s** wall time and 23 MB RSS, on git 2.53.0. 120 s is more than 1,000 times that.
- **Symmetric with fetch.** It equals `FETCH_BUDGET_SECONDS`, so each phase of a `verify` is bounded alike.
- **Worst case.** The check runs before each call, so a call already in flight can overrun the deadline by up to `GIT_TIMEOUT_SECONDS`. The worst-case binding phase is therefore 180 s. Bounding the in-flight call as well would change the `_run_git` seam signature; that is not done (stated).

**Why 16 MiB, and why a new code.**
- **Headroom.** The largest tracked file in this repo is 896 KiB (`docs/v0.7.0/TECHNICAL-DESIGN-1540-S1-S2-intake-trust-gate.md`), and this branch's whole-file patch is 436 KiB. 16 MiB is about 18 times the first and 37 times the second. Only a step that touches many very large or binary files reaches it, and nobody reviews such a step line by line.
- **The code.** It is a new `patch-too-large`, not `git-failure`. Git did not fail, and the operator's remedy, splitting the step, is different. It reaches exit 3 through the existing `VerifierError` path.

#### 10.4.7 If ARCH-Q-S1b is ruled R: the delta from §10.4.3 to §10.4.5 (NOT ADOPTED, R-A8; retained for the record. The coder does not build any of this.)

- There is no `_run_gh_graphql`, no `DELETIONS_QUERY` and no `CURSOR_RE`. §2 keeps three seams.
- **Read 6.**
  - The endpoint is `_run_gh_get(f"repos/{repo}/issues/{number}/timeline?per_page=100&page={k}")`, for `k = 1 … DELETION_PAGE_BOUND`.
  - The read-4 page rules apply: each page is a list; a page with fewer than 100 items ends the loop; a full last page is `pagination-bound`.
  - Every item must be a dict. An item with `event == "comment_deleted"` must have an int `id` > 0 that is not a bool, and a `created_at` str that fullmatches `TS_RE`; otherwise `payload-shape`. Other items are ignored.
  - Each deletion becomes `Deletion(id, created_at, None, number)`.
- `decide` is unchanged. Every `author_login` is `None`, so every deletion at or after the act qualifies.
- **R-S1b-3.** The REST listings omitted 11 of 58 events, with no signal (§10.4.1). A bot deletion missed that way silently resurrects the older act. This is the HQ-1 case and cannot be detected, so under R **the human must accept R-S1b-3 on their own account before S2 merges.**
- **Tests.** T-F-15 to T-F-21 are rewritten for the timeline GET. T-P-34 (`author=None`) becomes the only author case that applies.

#### 10.4.8 Scope, residuals, reviewers, self-flag

**Files.** No new file (§1). The edits are to `human_authorization.py`, the predicate, binding, fetch and CLI tests, the findings file, and this TD. The branch stays at 14 files.

**Residuals.**
- **R-S1b-1.** A CODEOWNER deleting their own comment is probably not recorded (0 of 41 attributable events had the deleter equal to the author), so deleting their own newer decline lets their older authorize govern. This is the human's own act on their own account, not the bot attack HQ-1 addresses. It is disclosed, not mitigated.
- **R-S1b-2.** GraphQL completeness is measured only against REST (REST's 47 events are a subset of GraphQL's 58), and GraphQL was the discovery source. An App deleter was observed only on PR threads (5 of 5). A controlled write test would settle R-S1b-1 and R-S1b-2: a human posts a comment on a scratch issue, the worker App deletes it, and both transports are read. That test needs a human-authorized write. **S2-PRE-6, made binding by R-A8 (§10.4.9): it blocks S2's merge, not S1b.**
- **R-S1b-3.** Applies only under option R (§10.4.7).
- **R-S1b-4.** The size cap is checked on bytes already captured, so one oversize git output is held in memory once before the refusal. Bounding that peak would need streaming reads in the `_run_git` seam; S1b does not do this.

**S2-PRE-1.** It is satisfied when S1b merges under G (ruled, R-A8). The R branch of this sentence is moot.

**Reviewers.**
- `security-reviewer`: `decide`, read 6 and the new transport.
- `privacy-reviewer`: the new detail value and the new transport.
- `reliability-reviewer`: the budget, the cap and the extra calls.
- `code-reviewer` and `unit-test`.
- The codex second review, scoped to the S1b commits.
- The architect: ARCH-Q-S1b and this section.

**Self-flag (this design change).**
RISK: HIGH. It changes the sole human-gate predicate and adds a trust-path read (under G, a second transport).
CONFIDENCE: HIGH on the field shapes and the REST omission (live reads, 58 events, ids cross-checked). HIGH on the soundness of the `≥ g.created_at` rule. MEDIUM on GraphQL's completeness (R-S1b-2) and on self-deletion (R-S1b-1), neither testable read-only.
BLAST RADIUS: `decide`, `fetch`, `compute_binding` and their tests. There is no runtime caller until S2.
Change classification: **additive** (fail-closed). The transport choice is routed to the architect as ARCH-Q-S1b.

#### 10.4.9 Architect ruling R-A8 (2026-10-30): ARCH-Q-S1b is G. §10.4 is approved with the changes below.

**Verdict: APPROVED WITH CHANGES.** The changes are mechanical and are applied in this document, marked "(R-A8)". No further technical-design round is needed. S1b may go to `coder`.

**R-A8.1. The transport: G.** The deletion read is the fixed, read-only GraphQL query `DELETIONS_QUERY` behind the fourth seam `_run_gh_graphql`, built as §10.4.3 and §10.4.4 specify. Option R (§10.4.7) is not adopted. A union of R and G is also not adopted.

**R-A8.2. A silent REST omission counts as "REST lacks it".** This reading follows from R-A1 and from #2151.
- R-A1 preferred REST *as a fail-closed input*. The issue text says GraphQL is used "only if REST lacks it". For a trust input, "exposes the event" means exposes it in a form whose absence can be told apart from a gap. A listing that drops 11 of 58 events (11 of 40 on PRs), with no marker, while the same events are retrievable by id, does not meet that bar. A missing event is a fail-open input, not a weaker signal.
- R also contradicts HQ-1 as worded. The human said "refuse fail-closed if deletion can't be detected". Under R the verifier cannot tell whether it detected a deletion. Read strictly, HQ-1 would then force a refusal of every act, which makes the gate unusable. Read loosely, it would need a new human acceptance of R-S1b-3. G avoids both.
- So G is the path R-A1 already pre-authorized: GraphQL, read-only, fail-closed. It is not a new architecture decision that reopens R-A1.

**R-A8.3. Product-boundary checkpoint: no new human question for G.**
- *User-visible behaviour.* The new refusals (`deleted-later`, and exit 3 when the deletion read fails) are the behaviour HQ-1 cleared. G's over-refusal set (§10.4.5) is narrower than the "refuse every act" fallback HQ-1 accepted.
- *Trust boundary and topology.* G uses the same host (`api.github.com`), the same `gh` binary, and the same installation token and identity. GraphQL is already an established transport in this repo (`scripts/automation/lib/merge_authority.py:1237`, `bootstrap/post_review_thread.sh`), and those uses are *mutations*. G is a query.
- *Cost and operations.* G adds one GraphQL point per source per `verify` against a separate rate-limit pool. That is negligible.
- *Retention.* G adds no persisted data. The only new output is `event:<databaseId>`.
- Nothing here crosses the checkpoint, so no human question is needed.

**R-A8.4. Correction: `filteredCount` is a pagination-integrity check, not an independent completeness check.** The count and the nodes come from the same server and the same query. The check catches truncated pages, a dropped page and a count that moves during the read (a concurrent deletion gives exit 3, closed, and a retry resolves it). It cannot catch an event that GraphQL's own index omits.
- That residual is R-S1b-2. The probe cannot bound it, because GraphQL was the discovery source.
- The App-deletes-a-User shape was observed only on PRs (5 of 5). Acts live mostly on step **issues**.
- Both points are why S2-PRE-6 becomes binding (R-A8.6). §10.4.2 is amended to say this.
- *Why I do not keep REST as a cross-check under G.* A REST-listed event that GraphQL lacks would be a real alarm. But none was observed (47 of 47 REST events were also in GraphQL). Cross-checking would also put the `/timeline` GET on the trust path, and on long PR threads (2,466 items on `rust#112049`) it hits `DELETION_PAGE_BOUND` and gives a permanent exit 3. The write test answers the same question once, directly.

**R-A8.5. The rest of §10.4, critiqued.**
- **The `deleted-later` rule (§10.4.5): correct, and the soundness argument holds.** Neither transport gives the deleted comment's creation time. So "deletion time ≥ governing act's `created_at`" is the tightest sound filter: a comment deleted before the act existed before it, so it could never have been a newer participant.
  - The `≥` correctly covers the same-second tie that the `(created_at, id)` order could resolve either way (T-P-33).
  - "CODEOWNER or unknown author" is the minimal sound author filter, because only a verified CODEOWNER's comment can be a participant.
  - Leaving out the bot exclusion is right. GraphQL `Bot.login` drops the `[bot]` suffix, so an App slug can equal a human login. The worst case is an over-refusal.
  - *What could still go wrong:* the comparison is a plain string compare. It is sound only because both sides fullmatch `TS_RE` (whole seconds, `Z`). If GitHub ever returns fractional seconds or an offset on either side, the fullmatch fails with `payload-shape`, which is closed. The coder must not "relax" `TS_RE` to accept such forms without converting both sides to one canonical form first.
  - Placement in the accept branch only is correct. Every other branch is already unmet, and adding a second reason there would break AD-10's one event per candidate (T-P-41).
- **Read order (§10.4.4): correct and load-bearing.** Deletions are read after comments, so a deletion between the two reads lands in the second. Any later deletion is caught by the overseer's re-verify (AF-5).
  - *What could still go wrong:* a refactor that parallelizes or reorders the reads. T-F-16 pins the order and must stay a hard assertion, not a sorted comparison.
- **Required keyword-only `deletions`, with no default (§10.4.5): correct.** A forgotten argument is a `TypeError`, which becomes exit 3, never a skipped check. The element-type `ValueError` stops a caller passing raw dicts. Approved as drafted.
- **`BINDING_BUDGET_SECONDS = 120` (§10.4.6): approved.** The measured run took 0.08 s, which is three orders of magnitude of headroom. The value matches the fetch budget. The stated 180 s worst case, from one in-flight call overrunning by `GIT_TIMEOUT_SECONDS`, is acceptable.
  - Not bounding the in-flight call is correct for S1b, because it would change the `_run_git` seam.
  - *What could still go wrong:* an S2 caller that wraps `verify` in its own timeout. See S2-PRE-7.
- **`BINDING_BYTES_MAX = 16 MiB` and the new code `patch-too-large` (§10.4.6): approved.**
  - The size headroom is about 18 times the largest tracked file.
  - A separate code is right: the remedy (split the step) differs from `git-failure`'s, and the value is additive to a closed set.
  - The cap checks every rung and the cumulative old-blob bytes. Because the cache is hoisted, the cumulative total counts each blob once. That is correct.
  - *Coder note:* keep a running byte total instead of re-summing `blobs.values()` after each insert. The behaviour is the same, and the cost is O(1) rather than O(n²).
  - R-S1b-4, the in-memory peak before the refusal, is accepted. An out-of-memory kill leaves the process exit status non-zero with no valid JSON, and under R-A2 that clears no item, so it is closed.
  - *Product-boundary classification:* "this step can never be authorized" is a user-visible failure mode. It is a disclosure, not a gate: it only refuses more, and the remedy is splitting the step, or raising the constant through a human-approved PR to a protected file. It is disclosed in the Human Review Required section.
- **`_git_budgeted` as the only caller of `_run_git` (T-B-21): correct.** I re-read §4.7 and §4.9. Every git call in the module is inside `compute_binding` and its helpers, and the `--repo-root` work-tree check is `compute_binding`'s first `_run_git`. So the static rule is satisfiable without carving out an exception. If the coder finds a git call outside `compute_binding`, that is a design question to raise. It is not a reason to add an exemption to T-B-21.

**R-A8.6. Coder and test obligations added by R-A8. Same files; no new file.**
1. **T-F-21, extended.**
   - `DELETIONS_QUERY` is asserted **byte-equal** to the §10.4.3 literal, written out in the test. "Does not contain `mutation`" alone would let a widened query through.
   - The query does not contain `body`, `actor` or `author` outside `deletedCommentAuthor`. This is privacy minimization: the decision needs no deleter identity, and no body text may ever be fetched.
   - `_run_gh_graphql` is the only function whose argv contains `"graphql"`.
2. **T-F-18, two more rows.** A `nodes` list containing `null`, which GraphQL returns on partial errors, gives `payload-shape`. `timelineItems: null` gives `payload-shape`.
3. **T-F-19b (new).** Page 1 says `filteredCount 101` with `hasNextPage true`, and page 2 says `filteredCount 102`. The result is `payload-shape`, because the count moved during the read.
4. **Module docstring.** It names R-S1b-1, R-S1b-2 and R-S1b-4. It also says that `filteredCount` is a same-source integrity check and not a completeness proof.
5. **The §10.4.5 rule is built as drafted, including the `≥`. No narrowing.**

**R-A8.7. S2 prerequisites (none blocks S1b).**
- **S2-PRE-6 (made binding by R-A8; it was "recommended"):** before S2 merges, the controlled write test of R-S1b-2 must run on a scratch **issue** in this repo. A scratch PR is optional.
  1. The human posts one comment from their own account. The worker App deletes it.
  2. Both transports are read. The test passes iff GraphQL returns a `CommentDeletedEvent` with `deletedCommentAuthor.login` equal to the human's login and `createdAt` equal to the deletion time.
  3. In the same session, the human deletes one comment of their own, and the record is read. This settles R-S1b-1.
  - If the App deletion is **not** recorded by GraphQL, the G design is unsound for issues. S2 does not merge, and the question returns to the architect.
  - If the human declines to authorize the write, S2 may merge only with the human's own-account acceptance of R-S1b-2 for live use. That is HQ-3's "No" branch.
- **S2-PRE-7:** any S2 caller that runs `verify` under its own wall-clock timeout must set it above the worst case (fetch about 150 s, binding about 180 s, plus audit writes). It must also treat a timeout as "no item cleared", which R-A2 already requires. S2's design states the number.
- **S2-PRE-8 (blocks S2 merge, not S1b; architect ARCH-R-2151-1):** confirm how GitHub treats an escaped `\#` and a mid-token `#` in CODEOWNERS (docs plus a CODEOWNERS-errors API probe). GitHub lists escaping a leading `#` among unsupported gitignore features, so `\#notes.md @bob` may be a comment there, while R-A7's strict parser returns `bob`. Until confirmed, S2's security review must re-check R-A7 against it; the verifier's fail-closed default is to drop owners on any line whose path token contains `#`, escaped or not.
- **S2-PRE-3, extended:** a consumer on a GitHub host whose GraphQL schema lacks `CommentDeletedEvent` gets exit 3 on every `verify`. That is closed, but the gate is unsatisfiable there. S2 lists "GraphQL `CommentDeletedEvent` available" in the consumer prerequisites, next to the minimum git version.

**R-A8.8. Startup-gap and affected-sign-offs analysis.**
- *Should this have been settled in the initial architecture review?* **No new gap.** R-A1 deliberately deferred the transport until a probe existed, and named GraphQL as the fallback. The probe falsified R-A1's working assumption that the REST listing is complete. That is the outcome R-A1's conditional was written to handle, not a missed decision.
- *Affected sign-offs.* No code was built against option R, so no approval is orphaned. §11's S1b re-review list stands as written. It already covers `fetch`, the new transport (security and privacy), `decide` and `compute_binding`. To that list R-A8 adds one item: `security-reviewer` confirms the T-F-21 byte-equality pin and the field-minimization assertions (R-A8.6 item 1).
- The ADR-2101 erratum that S2 records in `DECISIONS.md` (R-A2, R-A6) also names R-A8: a second, read-only transport on the trust path.

**R-A8.9. Open human question (it blocks S2's merge, not S1b coding or the S1b merge).**
- **HQ-3:** "Before the verifier goes live in S2, do you authorize a one-time test in this repo? On a scratch issue, you post one comment and the worker App deletes it. Then you delete one comment of your own. The worker reads both APIs to confirm GitHub records each deletion and its author. Answer **Yes**, or **No**. No means you accept, for live use, that GraphQL's completeness for deletions on issues is unverified (R-S1b-2)."
- HQ-1 already answers what to do when a deletion cannot be detected. HQ-3 asks only whether to run the test that checks the detector itself.

---

## 11. Startup-gap check and affected sign-offs

- **Should this have been settled in the initial design?** The startup gap for #2101 as a whole is already recorded in ADR-2101 §6, with a recommendation to open or annotate a `startup-artifact-gap` issue. This TD is the first design of S1, not a reactive change to an approved contract, so it raises **no new startup gap**.
- **Affected sign-offs.** None. No code has been approved against an earlier S1 contract.
  - The `requester_trust.py` extractions are behaviour-identical, and their tests pin that. The #1540 S1 sign-offs on `requester_trust.py` stand.
  - The one conformance test edited (§3.4) widens an allow-set by one *delegating* reader, with stronger assertions, so the #1540 sign-off on that test stands.
  - `security-reviewer` should still confirm, on the S1 PR, that `codeowners_humans` and `load_bot_accounts` are unchanged.
- **§10.2 amendments (2026-10-22).** These are reactive, but they record fixes made *during* S1 review, before any S1 approval was final, and they are fail-closed refinements, not missing contract. No new startup gap. The S1 reviewers who raised them re-review `05cf44cb1`; no other sign-off is affected.
- **§10.3 R-A6 (2026-10-22).** *Should this have been settled in the initial architecture review?* **Yes.** AD-5 chose `patch-id` for its merge-survival property and did not examine what `patch-id` discards (hunk positions). This is a startup-artifact gap in ADR-2101 AD-5. The worker annotates the existing #2101 startup-gap record (ADR §6), since the architect files no issues in this invocation. *Affected sign-offs:*
  - **Invalidated:** every S1 sign-off that covers `compute_binding` or `test_human_authorization_binding.py`, namely `security-reviewer`, `code-reviewer`, `unit-test`, and the codex/agy second-review verdicts. They approved a binding that the revised §4.7 supersedes, so each must re-review the R-A6 commit.
  - **Stand:** the `privacy-reviewer` and `reliability-reviewer` sign-offs stand, because R-A6 adds no output channel and only bounded git calls under the existing timeout. The parse/render, `decide`, fetch and CLI sign-offs also stand, because R-A6 changes no interface they rely on. The `requester_trust` sign-offs stand.
  - **ADR-2101:** the human's ESC-3 ruling stands as worded (§10.3).
- **§10.3 R-A7 (2026-10-22).** *Should this have been settled in the initial review?* **Partly.** The defect predates #2101: it was moved from `probe.py:_codeowners_humans`. But this TD's §3.1 chose to move it verbatim when AD-3 made it a sole-gate input. *Affected sign-offs:*
  - **Invalidated:** the #1540 S1 sign-offs that approved `codeowners_humans` as "byte-identical", and this S1's `security-reviewer` and `code-reviewer` sign-offs on §3.1. They approved behaviour that R-A7 deliberately changes, so each must re-review.
  - **Stand:** the `select_work_candidates.py` and `probe.py` logic sign-offs. Their code is unchanged, apart from one remediation string, and their contract (a set of human logins) is preserved. Their existing tests (`test_requester_trust.py:114-174`, `test_probe.py:481-488`) still hold.
- **§10.3 R-A7a (2026-11-18).** *Should this have been settled in the initial design?* **Yes.** It is a gap in R-A7's own rule 3, which this TD wrote, and which contradicted the existing "`#` anywhere" pin. The worker annotates the existing #2101 startup-gap record; this agent files no issues. *Affected sign-offs (#2151 is unmerged, so these are pending re-reviews):*
  - **Must re-review:** `security-reviewer` and `code-reviewer` on `parse_codeowners_humans` (they approved the starts-with rule); `unit-test` on the new rows; and the second review, scoped to the R-A7a commit, before the final full-range run.
  - **Stand:** the `merge_authority` delegation, `approval_merge`, selector, trust-set and probe sign-offs. The callers are unchanged, the set only shrinks, and every existing expected set holds. The `human_authorization` sign-offs outside the one new regression test also stand.
- **§10.4 S1b (2026-10-30).** *Should this have been settled in the initial technical design?*
  - **R-S1-5: no new gap.** It was identified in the initial design (ARCH-Q1), deliberately deferred by R-A1 with an explicit gate on S2, and is now closed on schedule. No `startup-artifact-gap` issue is needed.
  - **The binding budget: partly.** R-A6 (§10.3) multiplied the git calls (5 rungs, with per-rung blob reads) without carrying over `fetch`'s budget pattern. That is a gap in the R-A6 amendment, not in the original contract. The worker should annotate the existing #2101 startup-gap record. This agent files no issues.
  - *Affected sign-offs (S1 is unmerged, so these are pending re-reviews, not invalidated merges):*
    - **Must re-review the S1b delta:** `security-reviewer`, `code-reviewer` and `unit-test` on `decide` (new argument, new branch), `fetch` (read 6) and `compute_binding` (budget, cache, cap); `reliability-reviewer` on the budget and cap, which closes its own SHOULD_FIX; `privacy-reviewer` on the new detail value and, under G, the new transport; and the codex second review, scoped to the S1b commits.
    - **Stand:** the parse/render and `render_request` sign-offs (unchanged code, and T-PR-* unchanged); the audit and `--audit-on-change` sign-offs (no new event kind or field, only a new closed-set value); and the `requester_trust` and selector sign-offs.

---

## Escalation flag (CORE self-flag)

RISK: HIGH. This module becomes the sole decision point for the CRITICAL and structural human gates, on a protected surface. A defect in `decide` (§4.6), the actor rule or the binding is a bot-satisfiable gate.
CONFIDENCE: HIGH on the reuse citations, the binding behaviour (local experiment, §4.7) and the probe results (§5, live reads this session). MEDIUM on ARCH-Q1's real-world exposure: I did not probe REST or GraphQL deletion-event visibility.
BLAST RADIUS: in S1, none at runtime: the module has no caller. Two `requester_trust.py` functions are refactored behind unchanged signatures. One conformance test is widened. In S2, every gated step's path to a PR.
Change classification: **additive** (S1). It implements a human-approved STRUCTURAL ADR. The refinements in §10 are additive or clarifying. ARCH-Q1 and ARCH-Q2 are routed rather than decided silently.

## Human Review Required

The S1 PR lands on `scripts/framework/**`, so your own-account approval of the protected-surface PR is the final gate. The architect answered ARCH-Q1 to ARCH-Q7 (§10.1). Two human questions are open. Neither blocks S1 coding or the S1 merge, because S1 has no caller. Both block S2's merge: **HQ-1**, whether to accept deletion resurrection (R-S1-5) if the REST mitigation is impossible (*answered 2026-10-22: refuse fail-closed; built by S1b, §10.4; HQ-3 below replaces it as the open deletion question*), and **HQ-2**, whether any later edit of your own comment should void your authorization. S2-PRE-3, consumer provisioning of `machine-accounts.env`, also needs your clearance before S2. REQ-2 and REQ-9 are not open to any answer.

**Disclosure (R-A6, §10.3; no answer needed).** The binding now widens its diff context when an edit's surrounding lines appear more than once in the same file. Without this, an authorization for one edit would also cover the identical edit at another place in that file (reproduced). For such steps only, a merge from `main` that edits nearby lines (within 10, 30 or 100 lines, or anywhere in the file at the last rung) voids your authorization, and you post a fresh one. This is the same kind of over-refusal you accepted in ESC-3 (R-2), over a wider window, and it never makes an authorization cover more.

**Disclosure (R-A7, §10.3; no answer needed).** The shared CODEOWNERS reader now counts only `@username` owner handles, stops at the first owner token that contains a `#` (an inline comment, even one written without a space, as in `@alice#`; amended 2026-11-18, R-A7a), and honours escaped spaces in paths. Before this, a comment word after an owner (for example `alice` in `* @maintainer # alice handles triage`) counted as a human authorizer. Today the selector, the trust set and the needs-ai probe all use this reader, and S1's verifier will too. This repository's CODEOWNERS still yields exactly you.

**S1b (§10.4, #2151): your HQ-1 ruling, as built.**
- If one of your comments on the step's issue or PR is deleted at or after your latest authorization, that authorization is void until you post a fresh one (reason `deleted-later`). A deletion of a comment whose author GitHub no longer knows (a deleted account) counts too.
- If the verifier cannot read the deletion record completely, it decides nothing (exit 3).
- **The architect ruled ARCH-Q-S1b = G (R-A8, §10.4.9).** Deletions are read through GitHub's GraphQL API, which names the deleted comment's author. REST alone was not used, because it was seen to omit about 1 in 5 deletion events (11 of 58) with no signal. No new answer is needed from you for S1b.
- **Disclosure (no answer needed).** Deleting your *own* newer decline is probably not recorded by GitHub, so your earlier authorize would stand again (R-S1b-1). That is your own act.
- **HQ-3 (R-A8.9; it blocks S2's merge, not S1b).** A one-time write test on a scratch issue, which needs your authorization: you post a comment, the worker App deletes it, you delete one comment of your own, and the record is confirmed. Answer Yes, or No. No means you accept that GraphQL's completeness for deletions on issues is unverified (R-S1b-2) for live use.
- **Also disclosed.** A step whose patch exceeds 16 MiB now fails closed with `patch-too-large`, and must be split.
