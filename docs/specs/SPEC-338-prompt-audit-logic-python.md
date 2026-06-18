# SPEC-338: Move prompt_audit.sh stats aggregation and commit-body parsing to Python

**Status:** Draft — for architect review
**Issue:** #338
**Policy:** #314 — prefer Python for logic, shell for launch; testability is a code review criterion
**Date:** 2026-06-17

---

## 1. Problem statement

`scripts/prompt_audit.sh` implements a prompt-artifact audit query tool with three modes: `list`, `pending`, and `stats`. The `stats` mode performs statistics aggregation over git commit history and the `prompts/` directory; the `list` mode extracts and formats prompt-artifact data from git commit bodies. Both operations are currently implemented entirely in bash with `git log --grep`, `wc -l`, `grep -rl`, `find`, and `cut`.

Per policy #314 — "shell scripts should be launchers, not logic containers" — this logic is difficult to test in isolation: verifying the stats aggregation or commit-body parsing requires a real git repository with specific commit history. There is no unit test surface. A Python module with the same logic can be tested against a fixture repository or mock git output without spawning a live git process.

---

## 2. Current behavior (per `scripts/prompt_audit.sh`)

### Mode: `list` (default)

Invoked with no arguments, or with `--risk <LEVEL>`.

- **With `--risk <LEVEL>`:** runs `git log --grep="AI-Risk: <LEVEL>" --pretty=format:"%h %ad %s" --date=short` and prints the first 40 matching commits.
- **Without `--risk`:** runs `git log --grep="Prompt-Artifact:" --pretty=format:"%h %ad %s\n  <body>" --date=short` and prints the first 60 matching commits. The body extraction on line 33 uses a subshell `$(git log --pretty=format:'%b' -1 %H 2>/dev/null | grep 'AI-Risk:' || echo '')` — this is a per-commit subprocess inside the `--pretty=format` string, which is evaluated by the shell during format expansion. This is the primary "commit-body parsing" logic to move.

### Mode: `pending`

Scans the `prompts/` directory for `*.md` files containing the string `⬜ Pending` and prints their paths plus a count. Uses `find prompts -name "*.md" -print0` and `grep -q "⬜ Pending"`.

### Mode: `stats`

Aggregates the following metrics and prints them:

| Metric | How computed |
|---|---|
| AI-assisted commits (all time) | `git log --grep="Prompt-Artifact:" --oneline \| wc -l` |
| Commits by risk level (LOW/MEDIUM/HIGH/CRITICAL) | For each level: `git log --grep="AI-Risk: <LEVEL>" --oneline \| wc -l` |
| Total prompt artifacts | `find prompts -name "*.md" \| wc -l` |
| Pending review | `grep -rl "⬜ Pending" prompts \| wc -l` |
| Approved | `grep -rl "APPROVED" prompts \| wc -l` |

All counts are whitespace-trimmed with `tr -d ' '`. When the `prompts/` directory does not exist, the directory-dependent metrics are skipped and a "No prompts/ directory found." message is printed.

---

## 3. Scope

### What moves to Python (`scripts/oversight/prompt_audit_logic.py`, new module)

| Logic | Current location | Target function |
|---|---|---|
| Commit-body parsing — extract `AI-Risk:`, `Prompt-Artifact:`, `AI-Model:` trailers from `git log` output | `prompt_audit.sh` lines 29–35 (list mode) | `parse_commit_trailers(git_log_output: str) -> list[dict]` |
| Stats aggregation — count commits by grep pattern, count artifact files by status | `prompt_audit.sh` lines 63–82 (stats mode) | `compute_stats(repo_root: str) -> dict` |
| Pending scan — find `prompts/*.md` files containing `⬜ Pending` | `prompt_audit.sh` lines 47–55 (pending mode) | `find_pending_artifacts(prompts_dir: str) -> list[str]` |

### What stays in shell (`scripts/prompt_audit.sh`)

- Argument parsing (`--risk`, `--pending`, `--stats`)
- Invoking `python3 scripts/oversight/prompt_audit_logic.py` with appropriate arguments
- Printing headers ("AI-assisted commits:", "Prompt Artifact Statistics", etc.)
- All `git log` subprocess invocations (the shell remains the process launcher; Python parses the output)

**Clarification on commit-body parsing scope:** The shell currently embeds a `git log` invocation inside a `--pretty=format` string. The Python module is not responsible for running `git log` — the shell runs `git log` and passes its stdout to Python for parsing. Python must not spawn git processes itself (to preserve testability with fixture input).

---

## 4. Requirements

**R1 — Extract `parse_commit_trailers`.** `prompt_audit_logic.py` must expose a function (or CLI entry point) that accepts `git log` output as a string or stdin stream and returns structured data (list of dicts or similar) with at minimum: commit hash, date, subject, `AI-Risk` value, `Prompt-Artifact` path, `AI-Model` value. The shell script passes the output of `git log --format="%H %ad %s%n%b"` (or equivalent) to Python and Python extracts the trailers.

**R2 — Extract `compute_stats`.** `prompt_audit_logic.py` must expose a function (or CLI entry point) that computes all metrics currently computed in `stats` mode: total AI-assisted commits, per-risk-level counts, total artifacts, pending count, approved count. The shell script passes `git log` output and the `prompts/` directory path to Python; Python does not call `git` or `grep` itself.

**R3 — Extract `find_pending_artifacts`.** `prompt_audit_logic.py` must expose a function (or CLI entry point) that scans a given directory for `*.md` files containing `⬜ Pending` and returns their paths. The shell script passes the directory path; Python scans it.

**R4 — Unit-testable without a live git repository.** All three functions must be exercisable from a Python unit test by passing fixture strings or a tmp directory. No subprocess invocation inside the Python module. This is the primary testability goal of this refactor.

**R5 — Output parity.** The numbers produced by the Python stats aggregation must match what the bash implementation produces for the same repository. The architect should specify how this is validated (e.g., an integration test that runs both and diffs the output, or a manual spot-check before the bash implementation is retired).

**R6 — External interface unchanged.** `scripts/prompt_audit.sh` must continue to work as the user-facing entry point with the same flags (`--risk`, `--pending`, `--stats`) and produce the same human-readable output. The script becomes a thin launcher; the flags and output format are unchanged.

**R7 — Stdlib only.** `prompt_audit_logic.py` must not introduce third-party dependencies. All operations (string parsing, file scanning, counting) use Python stdlib only, consistent with `suspension_manager.py`.

---

## 5. Non-requirements

- This change does not add new query modes or new metrics.
- This change does not change the format of the stats output or the list output as seen by the user.
- This change does not modify the `prompts/` directory structure or the prompt artifact format.
- This change does not modify how `AI-Risk:`, `Prompt-Artifact:`, or `AI-Model:` git trailers are defined or written (that is the coder's concern at commit time).
- The pending-scan `⬜ Pending` string is preserved exactly as-is. This spec does not standardize the status string format.

---

## 6. Open questions for architect

**OQ-1 (git invocation boundary):** The current list mode embeds a per-commit `git log` subshell inside a `--pretty=format` string (line 33). The cleanest Python interface receives the full `git log` output (all commits, all trailers) in one pass and parses it. The architect should confirm the preferred git invocation strategy: (a) shell runs `git log --format="%H%n%ad%n%s%n%b%n---END---"` for all commits in one call and pipes to Python, or (b) shell loops commits and passes each body to Python individually. Option (a) is more testable and more efficient.

**OQ-2 (module placement):** The issue specifies `scripts/oversight/prompt_audit_logic.py`. This is consistent with the other `*_logic.py` modules in `scripts/oversight/`. The architect should confirm this path or redirect.

**OQ-3 (CLI vs. importable API):** Should `prompt_audit_logic.py` expose a Python importable API (functions) only, or also a `__main__` CLI that the shell calls? A CLI with subcommands (`--parse-trailers`, `--stats`, `--pending`) would allow the shell to remain simple. An importable-only API requires the shell to build a small calling script. Architect decision.
