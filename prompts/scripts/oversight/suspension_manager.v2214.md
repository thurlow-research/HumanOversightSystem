# Prompt artifact — suspension_manager.py + pr_readiness.py REQ-W-18 (#2214)

| | |
|---|---|
| **Source files** | `scripts/oversight/suspension_manager.py`, `scripts/automation/lib/pr_readiness.py`, `tests/oversight/test_suspension_timebox.py` |
| **Issue** | #2214 (implements the #2174 Q1 B human ruling, 2026-10-30) |
| **Design** | `docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md` (architect-approved round 1, ARCH-R1) |
| **Model** | claude-opus-5-5[1m] (worker session dispatching the `coder` subagent) |
| **Date** | 2026-11-06 |
| **Risk tier (declared)** | HIGH |
| **Human review** | required — protected surfaces (`contract/**`, evaluator/gate code); CODEOWNER approval of the PR is the authorization for the suspension (#2170) |

## Prompt given to the coder

Implement the code slice of the technical design
`docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md` (read it fully first,
including every `[ARCH-R1]` change; the TD is the contract — if anything is ambiguous,
stop and report the question rather than guessing).

Your files (and only these):
1. `scripts/oversight/suspension_manager.py` — the time-boxed grammar (`expires:`,
   `until-closed: #N`), the pure status classifier with injectable `today` and issue
   close-event lookup, the `--suspension-status` CLI and its exit codes, the
   `cmd_is_suspended` change (active-only), the manual-trace validator, the
   default-branch match (D-16), the tier/human-gate re-derivation (D-17), the D-15 ban
   on free-text `resolved:` for dep-mapper findings, the D-18 parser count cross-check,
   and `--check-suspended-resolutions`, all exactly as the TD specifies. Keep the module
   stdlib-only at import time; load the GitHub helper lazily inside the default lookup.
   No CLI flag may override the clock, the issue state, or the suspension-file path for
   the status/resolution checks.
2. `scripts/automation/lib/pr_readiness.py` — REQ-W-18 as the TD specifies, calling the
   real functions with no overrides (T-A4 pins this).
3. `tests/oversight/test_suspension_timebox.py` (new) — every test case the TD lists
   (acceptance (a)–(c) plus the ARCH-R1 additions), using a fixed clock and stubbed issue
   events; no network access and no writes outside pytest's tmp_path. Existing tests in
   `tests/oversight/test_suspension_manager.py` and the pr_readiness tests must still pass.

Do NOT edit `.claude/agents/*.md`, `contract/**`, or the TD — the worker session authors
those. Do not commit, stash, switch branches, file issues, or edit labels. Run
`scripts/oversight/.venv/bin/python -m pytest tests/oversight/test_suspension_timebox.py
tests/oversight/test_suspension_manager.py` and the pr_readiness tests and report results.
Self-flag per AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS) at the end.

## Refinement iterations

(none yet — iterations with code-reviewer are recorded in the sign-off register)

## Iteration 2026-11-13 — #2349 (human ruling A on #2214)

Authored directly by the worker session (model claude-sonnet-5-5) under the human's
instruction on #2214: "Fix validate_disclosure in this PR to compare the disclosure against
the validated trace (callers table, untraced items, authorizer, expiry), re-run the full chain
and a fresh full-range second review, and close #2349 with this PR."

Change: `validate_disclosure(handoff_text, step, trace_text, suspension_text)` now requires
the disclosed callers table (header and rows, in order) to equal the validated trace's,
every non-blank untraced line of the trace to appear, and the disclosed `Authorized by:`,
`expires:` and `until-closed:` to match the default-branch suspension. It fails closed when
the trace or suspension text is missing. `check_suspended_resolutions` passes both texts.
TD §5.3 updated to match.

## Iteration 2026-11-18 — AM-1 disclosure visibility allowlist (ruling A on #2214)

Model claude-opus-5-5 (coder subagent dispatched by the worker session). Design:
`docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md` AM-1 (architect-approved
round 3, ARCH-R3).

Prompt given to the coder: implement AM-1 (section 5.3 items 1-6 with R0-R7, P0-P5 and
P7-P9, V9 in `validate_dep_trace`, D-19/D-20/D-21, tests T-D1..T-D17) in
`scripts/oversight/suspension_manager.py` and `tests/oversight/test_suspension_timebox.py`;
flip or retire the existing tests the TD names; do not edit `.claude/agents/` or `contract/`;
do not change behaviour the TD does not specify; stop and report if the TD is ambiguous.

Change: `validate_disclosure` replaces the denylist (`_visible_markdown`, raw `]:` and `<`
scans, `_has_delimiter_row`) with an allowlist grammar over the raw section lines, a prefix
check (the fixed AI-Submitted block) and an exactly-once heading rule; the suffix is not
checked. `validate_dep_trace` splits lines on "\n" only and adds V9.

## Iteration 2026-11-18 — AM-2 default-branch freshness (codex CWE-362, residual R-7)

Model claude-opus-5-5 (coder subagent dispatched by the worker session). Design:
`docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md` §5.2.1 AM-2 (architect-approved
round 5, ARCH-R5), after the full-range second review's codex finding that S4 trusted a possibly
stale local `origin/<default>` ref.

Prompt given to the coder: implement §5.2.1 — `read_default_branch_suspension` replaces
`read_default_branch_blob`: `git ls-remote --symref --exit-code origin HEAD` (exact `HEAD` line
selection, branch-name validation, no local `origin/HEAD` read, no `main` fallback), compare with
the local `refs/remotes/origin/<D>` SHA, read with `ls-tree -z` + `show` at the verified SHA;
errors E-F1..E-F4 verbatim; `_git` gains an `env` overlay (`GIT_TERMINAL_PROMPT=0`, 60 s timeout);
required keyword-only `main_suspension_error` on `check_suspended_resolutions`; wire the CLI and
`pr_readiness` REQ-W-18; tests T-F1..T-F12 and extended T-A4; leave `--is-suspended`,
`--suspension-status` and the gate paths unchanged.

Follow-up prompts in the same iteration:
- Security MEDIUM (replace refs forge the blob at the verified SHA): `_git` always sets
  `GIT_NO_REPLACE_OBJECTS=1`; tests for a forged replace ref and a replace ref that empties
  `git diff`.
- Reliability (non-blocking): the CLI runs the origin lookup only when `suspension_applies`;
  test that no ls-remote call happens when APPLIES=no.
- Bandit B613: literal invisible/bidi characters replaced with `\u` escapes.
- Reliability: `_EMOJI_SHORTCODE_RE` made linear (overlapping lookahead candidate scan).

Change: S4 now fails closed unless the local default-branch ref equals origin's (narrows R-7);
adds network dependency R-10 on the evaluator and REQ-W-18 paths when a suspension applies.
