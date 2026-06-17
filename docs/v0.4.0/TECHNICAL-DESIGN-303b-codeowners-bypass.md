# Technical Design — SPEC-303b: CODEOWNERS Bypass Gap

**Document type:** Technical design (per-build-step contract)
**Spec:** `docs/specs/SPEC-303b-codeowners-bypass.md` (Issue #303, Finding 2)
**Issue:** #396 (team-entry policy sign-off — RESOLVED by architect ruling: GO)
**Companion:** `SPEC-overseer-merge-authority.md`
**Author:** technical-design
**Status:** APPROVED (architect ruling GO with bindings below)
**Change classification:** `additive` — a new gate layered on top of the existing
protected-surface gate; no existing approved contract is altered.

---

## 0. Architect bindings (binding, not advisory)

These resolve OQ-1..OQ-4 from the spec. They are contract, not suggestion:

1. **B1 — Team entries.** `@org/team` CODEOWNERS entries → unconditional
   `HUMAN_REQUIRED`. No membership expansion, no GitHub API call. (Resolves OQ-1.)
2. **B2 — Bot account source.** Bot accounts come from the `BOT_ACCOUNTS`
   environment variable — the same variable `require_human_approval.py` reads.
   No split definition. (Resolves R5 / OQ-3 ownership.)
3. **B3 — No caching.** CODEOWNERS is re-read on every invocation. No
   cross-invocation cache. (Resolves OQ-4.)
4. **B4 — Glob translation.** Reuse the `glob_to_regex` translation semantics from
   `require_human_approval.py` (lines 52–75) for pattern matching. (Resolves OQ-2:
   conservative, errs toward HUMAN_REQUIRED.)
5. **B5 — stdlib only.** No third-party dependency (`codeowners`/`gitpython` PyPI
   packages are rejected). (Resolves OQ-2 library question.)

---

## 1. Component map

New module: `scripts/oversight/codeowners.py` (stdlib only).

| Function | Signature | Contract |
|---|---|---|
| `load_codeowners` | `(repo_root) -> str \| None` | Read CODEOWNERS file text from the first existing location in priority order. Return `None` if none exists. |
| `parse_codeowners` | `(text) -> list[tuple[str, list[str]]]` | Parse CODEOWNERS text into ordered `(pattern, owners)` tuples. |
| `glob_to_regex` | `(glob) -> re.Pattern` | CODEOWNERS-pattern → anchored regex. Translation semantics per B4. |
| `get_owners_for_path` | `(entries, file_path) -> set[str]` | Return the owner set for the **last** matching CODEOWNERS entry (GitHub last-match-wins), else empty set. |
| `requires_human_approval` | `(file_path, entries, bot_accounts) -> tuple[bool, str]` | Per-file decision + reason. |
| `check_pr_files` | `(file_list, repo_root, bot_accounts) -> tuple[bool, list[str], str]` | PR-level aggregate: re-reads CODEOWNERS (B3), returns `(required, matched_paths, reason)`. |

---

## 2. Data contracts

### 2.1 CODEOWNERS file locations (priority order)

`load_codeowners(repo_root)` checks, in this exact order, and returns the text of the
**first** that exists:

1. `<repo_root>/.github/CODEOWNERS`
2. `<repo_root>/CODEOWNERS`
3. `<repo_root>/docs/CODEOWNERS`

Returns `None` when none exists. Reading is I/O only; no parsing here.

### 2.2 Parsed entry shape

`parse_codeowners(text)` returns `list[tuple[str, list[str]]]` — `(pattern, owners)`,
in **file order** (order is load-bearing: GitHub last-match-wins, see 3.1).

Parsing rules:
- Strip each line; skip blank lines and lines beginning with `#` (comments).
- Split on whitespace. First token = pattern. Remaining tokens = owners.
- A line with a pattern but **zero** owners is retained with an empty owners list
  (GitHub uses this to *clear* ownership for a pattern). It matches paths but
  contributes no owners — see 3.3 for how this resolves.
- Owner tokens are kept verbatim (e.g. `@user`, `@org/team`, `user@example.com`).

### 2.3 Owner classification (within `requires_human_approval`)

For the owner set of the matched entry:
- An owner of the form `@org/team` (contains exactly one `/` after the leading `@`,
  i.e. a slash anywhere after `@`) → **team owner** → `HUMAN_REQUIRED` (B1).
- An owner that is NOT in `bot_accounts` and is NOT a team owner → **human owner**
  → `HUMAN_REQUIRED`.
- An owner that IS in `bot_accounts` → bot owner (contributes nothing toward a gate).

`bot_accounts` is a `set[str]` supplied by the caller. The values are GitHub login
strings. For comparison, a CODEOWNERS owner token may carry a leading `@`; the bot
membership test strips the leading `@` before comparing (so `@HOSOversightTutelare`
matches a `bot_accounts` entry of `HOSOversightTutelare`). Email-form owners
(`user@example.com`) are treated as human owners (they are never bot logins).

---

## 3. Algorithms

### 3.1 Pattern matching — `get_owners_for_path(entries, file_path)`

GitHub CODEOWNERS semantics that this design honors:
- **Last matching pattern wins.** Iterate entries in order; the owners returned are
  those of the *last* entry whose pattern matches `file_path`.
- Pattern → regex via `glob_to_regex` (B4). The translation:
  - `**` → `.*` (cross-segment, matches `/`).
  - `*` → `[^/]*` (one path segment).
  - every other char → `re.escape`'d literal.
  - anchored `^...$`.
- **Leading-slash normalization.** CODEOWNERS patterns may begin with `/`
  (repo-root-anchored) — e.g. `/docs/`. Changed-file paths from a diff are
  repo-root-relative WITHOUT a leading slash. Before translating, a single leading
  `/` is stripped from the pattern so `/docs/x` and `docs/x` match identically.
- **Directory patterns.** A pattern ending in `/` (e.g. `docs/`, `contract/`) owns
  everything under that directory at any depth. It is treated as `docs/**` — the
  trailing `/` is replaced with `/**` before translation.
- **Bare-name / directory-name patterns.** A pattern with no slash and no glob
  (e.g. `build`) matches that name anywhere per GitHub; this design treats a plain
  no-slash, no-glob token `X` as `**/X` (match at any depth) so it errs toward
  matching (toward HUMAN_REQUIRED, B4/OQ-2). A pattern that already contains a slash
  is treated as repo-root-anchored (after leading-slash normalization).

Return: the owners list (as a `set`) of the last matching entry, or an empty set if
no entry matches.

### 3.2 Per-file decision — `requires_human_approval(file_path, entries, bot_accounts)`

Returns `(bool, reason)`:

1. `owners = get_owners_for_path(entries, file_path)`.
2. If `owners` is empty → `(False, "no CODEOWNERS entry")`.
   (Empty owners arises from BOTH "no matching entry" and "matched an
   ownership-clearing entry with zero owners" — both correctly resolve to not-gated,
   because there is no owner to protect.)
3. If any owner is a team owner (`@org/team`) →
   `(True, "team-owned path: <that entry>")` (B1). Team check is evaluated FIRST so a
   mixed `@org/team @bot` entry still gates.
4. Else if any owner is a human owner (not in `bot_accounts`) →
   `(True, "human CODEOWNERS owner: <that owner>")`.
5. Else (all owners are bots) → `(False, "bot-only CODEOWNERS entry")`.

Reason strings are stable and human-readable for the R4/R7 comment and log.

### 3.3 PR-level aggregate — `check_pr_files(file_list, repo_root, bot_accounts)`

Returns `(required: bool, matched_paths: list[str], reason: str)`:

1. `text = load_codeowners(repo_root)`. **Re-read every call (B3).**
2. If `text is None` → `(False, [], "no CODEOWNERS file")` (R1: skip + log; AC-5).
3. `entries = parse_codeowners(text)`.
4. For each `f` in `file_list`: compute `requires_human_approval(f, entries, ...)`.
   Collect `f` into `matched_paths` whenever the per-file result is `True`.
5. If `matched_paths` non-empty → `(True, matched_paths, <combined reason>)` where the
   combined reason names the triggering files and their owning entries (R4/R7).
6. Else → `(False, [], "no CODEOWNERS-human-owned path matched")`.

`check_pr_files` performs no GitHub I/O and no git I/O — `file_list` is supplied by
the caller (the overseer derives it from the PR diff). This keeps the module pure and
unit-testable with no network, mirroring `require_human_approval.py`'s local-test mode.

---

## 4. Boundaries

What this module MUST honor:
- **stdlib only** (B5). Imports limited to `os`, `re`, `pathlib`.
- **No caching** across calls (B3) — `check_pr_files` re-reads CODEOWNERS each call.
- **Errs toward HUMAN_REQUIRED** — when matching is ambiguous, prefer gating (B4/OQ-2).
- **No membership expansion** — never resolves `@org/team` to members (B1).
- **No git/gh/network** — pure function of `(file_list, repo_root, bot_accounts)`.
- **No mutation** of the overseer's existing protected-surface gate; this is additive
  (R3, AC-4). Both gates may fire; the overseer emits a single HUMAN_REQUIRED verdict.

What this module MUST NOT assume:
- Must not assume a CODEOWNERS file exists (AC-5 / R1).
- Must not assume `bot_accounts` is non-empty — an empty set means "no known bots",
  so every CODEOWNERS owner is treated as human (safe degradation, matches
  `require_human_approval.py`'s empty-BOT_ACCOUNTS behavior).
- Must not assume changed-file paths carry a leading slash.

---

## 5. Overseer integration (CORE edit)

In `overseer.md` CORE, within the merge-authority matrix section, BEFORE the matrix is
applied: the overseer calls `codeowners.py:check_pr_files` over the PR's changed files,
using `BOT_ACCOUNTS` from `machine-accounts.env`. If `required` is `True`, the verdict
is **HUMAN_REQUIRED regardless of risk tier or any other matrix input**, and the
overseer posts the R4 comment naming the matched files and CODEOWNERS entries. This is
additive to the existing protected-surface row (AC-4: both may fire; one verdict).

This is a CORE safety-tightening edit (adds a human gate; never removes one), so it is
permitted under the overseer's PROJECT-may-only-be-stricter rule and consistent with
"when in doubt, HUMAN_REQUIRED."

---

## 6. Acceptance-criteria traceability

| AC | Satisfied by |
|---|---|
| AC-1 | 3.3 step 6 — non-CODEOWNERS paths return `(False, [], ...)`; matrix unchanged |
| AC-2 | 3.2 step 4 — human owner → HUMAN_REQUIRED |
| AC-3 | 3.2 step 5 — bot-only → not gated |
| AC-4 | §5 + 3.3 — additive; both gates may fire, one verdict |
| AC-5 | 3.3 step 2 — no file → skip + reason, no regression |
| AC-6 | §2.3 / B2 — reads `BOT_ACCOUNTS`, not split vars |
| AC-7 | 3.3 step 5 / R4 — reason lists triggering files + entries |
| AC-8 | §4 / §5 — no merge on CODEOWNERS HUMAN_REQUIRED regardless of protected-surface |
| AC-9 | 3.2 step 3 / B1 — `@org/team` → HUMAN_REQUIRED, no expansion |

---

## Human Review Required

- **RISK:** MEDIUM — this is a safety gate. A false negative (failing to gate a
  human-owned path) would let the overseer auto-merge a path whose ownership intent is
  human-only — the exact field gap #303 Finding 2 reports. The design errs toward
  HUMAN_REQUIRED to make false negatives unlikely; the residual risk is false
  positives (over-gating), which are safe but could slow autonomous merges.
- **CONFIDENCE:** HIGH — the contract is small, pure, stdlib-only, and reuses the
  proven `glob_to_regex` translation. All four open questions are resolved by binding
  architect rulings.
- **BLAST RADIUS:** New module + one additive CORE edit to `overseer.md`. No change to
  `require_human_approval.py` or any existing approved contract. Existing sign-offs on
  the protected-surface gate stand (no startup-artifact-gap: this is net-new behavior
  the original design never claimed to cover).
