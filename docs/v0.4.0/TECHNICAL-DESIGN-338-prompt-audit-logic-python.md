# Technical Design — SPEC-338: Extract prompt-audit logic to `prompt_audit_logic.py`

**Spec:** `docs/specs/SPEC-338-prompt-audit-logic-python.md`
**Issue:** #338
**Policy:** #314 — shell launches, Python holds logic; testability is a review criterion
**Architect bindings applied:** 1–6 (see below)
**Status:** For architect review
**Date:** 2026-06-17

---

## 0. Architect bindings (authoritative — design conforms to these)

1. New module `scripts/oversight/prompt_audit_logic.py`.
2. One-pass git: the **shell** runs exactly ONE `git log --pretty=format:...` per Python invocation, using collision-proof separators `%x1e` (record / RS) and `%x1f` (field / US). No per-commit git calls anywhere.
3. The shell runs git; **Python never spawns git**. Python parsing functions take strings.
4. Module exposes BOTH an importable API (pure logic = the test surface) AND a `__main__` CLI shim (handles all I/O).
5. An **integration parity test is REQUIRED before the bash logic is deleted**: run the new launcher and (a captured snapshot of) the legacy logic on the same fixture and diff. Shipped as a test.
6. `find_pending_artifacts` and the file-scanning portion of `compute_stats` MAY do directory I/O; trailer-parsing and the counting/aggregation operating on git-log strings MUST be pure.

---

## 1. Contract overview

`prompt_audit.sh` keeps its three modes (`list` / `pending` / `stats`) and identical user-facing output. It becomes a launcher: it parses flags, runs the single git command for the mode, and pipes git stdout into `prompt_audit_logic.py <subcommand>`. Python parses, counts, scans, and emits the human-readable body. Headers may be emitted by either side; this design keeps headers in shell and bodies in Python (see §5) to minimise output drift risk.

---

## 2. Git invocation contract (shell → Python)

The shell emits records separated by RS (`\x1e`, `%x1e`) and fields within a record separated by US (`\x1f`, `%x1f`). These bytes never appear in commit hashes, dates, subjects, or trailer bodies, so they are collision-proof against arbitrary commit text.

### 2a. `list` (no `--risk`) and `stats` — full trailer pass

One git call:

```
git log --grep="Prompt-Artifact:" \
  --pretty=format:"%x1e%H%x1f%ad%x1f%s%x1f%b" --date=short
```

- Record `=` one commit, introduced by a leading `\x1e`.
- Fields, in order: `[0]` full hash `%H`, `[1]` short date `%ad`, `[2]` subject `%s`, `[3]` body `%b` (may contain newlines; the trailers `AI-Risk:`, `Prompt-Artifact:`, `AI-Model:` live here).

The leading `%x1e` means output begins with a separator; the parser discards the empty leading record. `%b` is last so embedded newlines cannot be confused with a field boundary (only US/RS are boundaries).

### 2b. `list --risk <LEVEL>` — filtered, no body needed

The legacy `--risk` path prints `%h %ad %s` only (no trailer body). One git call:

```
git log --grep="AI-Risk: <LEVEL>" \
  --pretty=format:"%x1e%h%x1f%ad%x1f%s" --date=short
```

Fields: `[0]` short hash `%h`, `[1]` date, `[2]` subject. No body field. The Python `list` subcommand handles a record with 3 or 4 fields (3 ⇒ filtered/no-trailer; 4 ⇒ full trailer pass).

> Note: the legacy filtered path used `%h` (short) while the unfiltered path used per-commit `%b`. To keep a single parser, both list variants feed the same `parse_commit_trailers`; the hash field is taken verbatim from git (`%h` filtered, `%H` unfiltered) — parity preserved because each variant is fed the matching git format.

---

## 3. Module: `scripts/oversight/prompt_audit_logic.py`

Stdlib only (R7). No `subprocess`, no `import git`, no network. Mirrors the `panel_logic.py` shape: pure functions + a `__main__` CLI shim that is the only I/O site.

### 3.1 `parse_commit_trailers(git_log_output, record_sep="\x1e", field_sep="\x1f") -> list[dict]` — PURE

Splits `git_log_output` on `record_sep`, drops empty records (the leading-separator artifact and any trailing whitespace-only record). For each record, splits on `field_sep` into up to 4 fields.

Returns a list of dicts, one per commit, each with keys:

| Key | Source | Notes |
|---|---|---|
| `hash` | field[0] | short or full per the feeding format; verbatim |
| `date` | field[1] | `%ad` short date; `""` if absent |
| `subject` | field[2] | `%s`; `""` if absent |
| `body` | field[3] | raw `%b`; retained so `compute_stats` can substring-match legacy `--grep` semantics |
| `ai_risk` | trailer scan of field[3] | value after `AI-Risk:`, stripped; `""` if none |
| `prompt_artifact` | trailer scan of field[3] | value after `Prompt-Artifact:`, stripped; `""` if none |
| `ai_model` | trailer scan of field[3] | value after `AI-Model:`, stripped; `""` if none |

**Trailer scan (pure, internal helper):** iterate the body's lines; for each target prefix (`AI-Risk:`, `Prompt-Artifact:`, `AI-Model:`), the first line whose stripped form starts with that prefix yields the remainder after the colon, stripped. Absent ⇒ `""`. Records with no body field (filtered `--risk` path, 3 fields) get all three trailer values `""`.

**Boundaries / invariants:**
- Empty input string ⇒ `[]`.
- Never raises on malformed records; a record with fewer than 3 fields still yields a dict with empty defaults for missing fields (defensive — git format guarantees ≥3, but parser does not assume it).
- Does not mutate inputs; performs no I/O.
- Separators are parameters (binding: testable with custom seps), defaulting to the RS/US bytes the shell uses.

### 3.2 `compute_stats(commit_list, prompts_dir=None) -> dict` — counting PURE; file scan I/O

Two responsibilities, cleanly split so the counting half is fixture-pure:

**(a) Commit counting — PURE, operates on `commit_list` (output of `parse_commit_trailers` over the union pass).** Counting mirrors legacy `git log --grep=<PATTERN>` **substring** semantics over the whole message (`subject` + raw `body`), NOT a stricter trailer-line interpretation. This is the exact-parity requirement (R5) and was verified necessary: real commit `a6eab266` mentions `Prompt-Artifact:` in PROSE (no trailer line) yet legacy `--grep` counts it, and `7308f6b` likewise. A trailer-only count produced `total=2` where legacy yields `3`. Therefore `parse_commit_trailers` retains the raw `body` field so `compute_stats` can substring-match.
- `total_commits` = count of records whose message contains `"Prompt-Artifact:"` (legacy `git log --grep="Prompt-Artifact:" --oneline | wc -l`).
- `by_risk` = dict over `LOW, MEDIUM, HIGH, CRITICAL`, each the count of records whose message contains `"AI-Risk: <LEVEL>"` (legacy `--grep="AI-Risk: <LEVEL>"`).

> **Parity note on `by_risk` / `total_commits` — VERIFIED against repo history.** Legacy ran two distinct record sets: `total_commits` from `--grep="Prompt-Artifact:"` and `by_risk` from `--grep="AI-Risk: <LEVEL>"`. These sets genuinely differ in this repo: commit `a6eab266` has `Prompt-Artifact:` but no `AI-Risk:`; commit `7308f6b` has `AI-Risk:` but no `Prompt-Artifact:`. A single `--grep="AI-Risk:"` pass would therefore UNDER-count `total_commits`. **Resolution (single git call, binding 2 honoured):** stats uses ONE git call with BOTH grep patterns — `--grep="Prompt-Artifact:" --grep="AI-Risk:"` — which git OR's into the UNION (verified: returns all 4 commits). Python then derives `total_commits` = count of records whose `prompt_artifact != ""` (verified == 3, legacy parity) and `by_risk` = count of records whose `ai_risk == LEVEL`. Both metrics are exact-parity from ONE git invocation. The earlier OQ is thereby RESOLVED in-design; no architect git-pass exception needed.

**(b) Artifact-file counting — I/O permitted (binding 6), only when `prompts_dir` is provided and exists:**
- `total_artifacts` = number of `*.md` files under `prompts_dir` (recursive), == legacy `find prompts -name "*.md" | wc -l`.
- `pending` = number of those files containing the exact substring `⬜ Pending` == legacy `grep -rl "⬜ Pending" prompts | wc -l`.
- `approved` = number of those files containing the exact substring `APPROVED` == legacy `grep -rl "APPROVED" prompts | wc -l`.

> `grep -rl` recurses over all files (not just `*.md`); `find -name "*.md"` is `*.md` only. Legacy used `grep -rl ... prompts` for pending/approved (all files) but `find -name "*.md"` for total. **Parity decision:** replicate legacy exactly — `total_artifacts` counts `*.md` only; `pending`/`approved` count ANY file under `prompts_dir` containing the marker (read as UTF-8, errors ignored). This preserves the existing numbers even though the file sets differ. Documented for the parity test.

Returns:
```
{"total_commits": int, "by_risk": {"LOW":int,"MEDIUM":int,"HIGH":int,"CRITICAL":int},
 "prompts_present": bool,
 "total_artifacts": int|None, "pending": int|None, "approved": int|None}
```
When `prompts_dir` is None or missing: `prompts_present=False` and the three file metrics are `None` (the shell/CLI then prints "No prompts/ directory found.", matching legacy).

**Boundaries:** counting half never touches the filesystem; only the artifact-file half does, and only under an existing `prompts_dir`. No git. Unreadable file ⇒ not counted toward pending/approved (errors swallowed, matching `grep ... 2>/dev/null`).

### 3.3 `find_pending_artifacts(artifacts_dir) -> list[str]` — directory I/O (binding 6)

Recursively walks `artifacts_dir` for `*.md` files; returns the sorted list of paths whose content contains the exact substring `⬜ Pending`. Missing directory ⇒ `[]`. Path strings are returned relative to the process CWD the same way `find prompts ...` produced them (i.e. prefixed by the passed `artifacts_dir`), preserving legacy output. Read as UTF-8 with errors ignored; unreadable files skipped.

> Parity with legacy `pending` mode: legacy iterated `find prompts -name "*.md"` then `grep -q "⬜ Pending"` — `*.md`-only. `find_pending_artifacts` matches that (`*.md`-only), unlike the stats pending metric (all files). The two legacy code paths genuinely differ; each Python function reproduces its own legacy path. Both behaviours are pinned by the parity test.

### 3.4 `__main__` CLI shim — ONLY I/O site (binding 4)

`argparse` with three subcommands (mirrors `change_classifier.py` subparser style):

| Subcommand | Reads | Args | Writes (stdout) |
|---|---|---|---|
| `list` | git log output on **stdin** | `--limit N` (default 60; 40 for filtered) | formatted commit lines |
| `stats` | git log output on **stdin** | `--prompts-dir PATH` (optional) | stats body |
| `pending` | nothing on stdin | `--prompts-dir PATH` (required) | pending paths + count line |

- `list`: reads stdin, calls `parse_commit_trailers`, prints up to `--limit` lines. Format per commit reproduces legacy: `"<hash> <date> <subject>"`, and when a non-empty `ai_risk` trailer exists, the legacy second line `"  AI-Risk: <value>"` is appended (legacy printed the raw grep'd `AI-Risk:` line indented two spaces; Python reconstructs `  AI-Risk: <value>`). Filtered `--risk` records (no body) print the single line only — parity with legacy filtered path which printed `%h %ad %s` with no second line.
- `stats`: reads stdin, calls `compute_stats(commit_list, prompts_dir)`, prints the body (the `══` header stays in shell, see §5.3).
- `pending`: calls `find_pending_artifacts`, prints `"  <path>"` per result then `"  <N> artifact(s) pending review"`.

Exit code 0 on success. Any parse error is non-fatal where reasonable; unlike `panel_logic` (a gate-adjacent enhancer that fails open), this is a reporting tool, so on an unexpected exception it prints nothing harmful and exits non-zero only if it cannot produce output (kept simple: defensive defaults mean it effectively always produces output).

---

## 4. Output-format parity table (load-bearing — the parity test asserts these)

| Mode | Legacy output (per line) | New output |
|---|---|---|
| `list` unfiltered | `%h %ad %s` then `  <AI-Risk: line or empty>` | `<hash> <date> <subject>` then `  AI-Risk: <v>` only when present |
| `list --risk` | `%h %ad %s` (≤40) | identical (≤40) |
| `pending` | header, `  <path>` per file, blank, `  N artifact(s) pending review` | identical |
| `stats` | header `══`, `AI-assisted commits (all time): N`, `  LEVEL: N` ×4, blank, artifacts block or "No prompts/ directory found." | identical |

One known **intentional cleanup**: legacy unfiltered `list` always printed the second indented line even when empty (a blank `  ` line) because of the subshell `|| echo ''`. The new code prints the second line ONLY when an `AI-Risk` value exists. This is a deliberate, documented deviation (removes spurious blank lines); the parity test treats the legacy empty trailing line as equivalent to its absence (normalised in the diff). **Flagged to architect** as the single behavioural difference — classified `clarifying`.

---

## 5. Shell launcher contract (`prompt_audit.sh` after change)

Resolves `REPO_ROOT` and the logic module path. Per mode:

**5.1 `list`:** run the matching git command (§2a unfiltered or §2b filtered) and pipe stdout to `python3 .../prompt_audit_logic.py list [--limit 40]`. Shell still prints the `AI-assisted commits:` header + blank line.

**5.2 `pending`:** if `prompts/` absent, print the legacy "No prompts/ directory found."-equivalent and exit 0 (the CLI handles empty gracefully too, but shell keeps the early header). Otherwise call `... pending --prompts-dir prompts`. Header stays in shell.

**5.3 `stats`:** run ONE git call `git log --grep="Prompt-Artifact:" --grep="AI-Risk:" --pretty=format:"%x1e%H%x1f%ad%x1f%s%x1f%b" --date=short` (two `--grep` = OR = union, verified), pipe to `... stats --prompts-dir prompts`. Shell prints the `Prompt Artifact Statistics` + `══` header; Python prints the metric body. (See §3.2: union pass feeds `total_commits` via `prompt_artifact` presence and `by_risk` via `ai_risk`.)

The shell performs the only git invocations; `set -euo pipefail` retained. `python3` resolution: prefer `scripts/oversight/.venv/bin/python` if present else `python3` (same pattern as `run_tests_inner_loop.sh`), so the launcher works in and out of the venv.

---

## 6. Test surface (binding 4 + 5)

New `tests/oversight/test_prompt_audit_logic.py` (loaded via `importlib.util` like `test_panel_logic.py`):

**Pure unit (default tier):**
- `parse_commit_trailers`: empty input → `[]`; single full record → all six keys; multiple records; missing trailers → `""`; body with embedded newlines and a trailer mid-body; filtered 3-field record → empty trailers; custom separators.
- `compute_stats` counting half: fixture `commit_list` → correct `total_commits` (records with `prompt_artifact`) and `by_risk` counts including zero levels; `prompts_dir=None` → file metrics `None`, `prompts_present=False`.
- `compute_stats` file half + `find_pending_artifacts`: use `tmp_path` — create `*.md` with/without `⬜ Pending` and `APPROVED`; assert counts and returned paths. (These touch disk but no git/network → default tier, fast.)

**Integration parity (`@pytest.mark.integration`, binding 5):** build a tiny fixture git log string (the RS/US format) + a `tmp_path` prompts dir; run the new `prompt_audit_logic.py` CLI via `subprocess` AND a captured/inlined reproduction of the legacy bash counting on the SAME fixture; diff normalised output (per §4 normalisation). Marked `integration` so it runs at release, not inner loop — consistent with `pyproject.toml` markers. This is the gate that licenses deleting the bash logic.

---

## 7. Affected sign-offs / startup-gap analysis

This is a refactor of an existing, previously-shipped tool. No prior sign-off is invalidated because external behaviour is unchanged (R6) except the single documented blank-line cleanup (§4), which never affected a reviewed contract. Not a `startup-artifact-gap`: the original `prompt_audit.sh` predates policy #314; this is the planned migration, not a missed initial-design decision.

---

## 8. Self-flag

RISK: LOW
CONFIDENCE: HIGH
BLAST RADIUS: `scripts/prompt_audit.sh` (reporting tool, not in any gate path), new `scripts/oversight/prompt_audit_logic.py`, new test file. No agent, no gate, no pipeline blocker consumes this output.

Change classification: **additive** (new module + tests) plus a `clarifying` behavioural tidy (§4 blank line). No `structural` change → no human gate required pre-write.

**Resolved design question (§3.2):** the legacy two-record-set divergence was verified real against repo history (sets differ by `a6eab266` and `7308f6b`). Rather than escalate, it is resolved within binding 2 by a single git call carrying BOTH grep patterns (union), with `total_commits` and `by_risk` derived from the per-record trailers. No architect git-pass exception required; no human gate (LOW risk, additive).
