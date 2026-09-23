# Prompt Artifact — test_vendor_argv_sweep.py

| Field | Value |
|---|---|
| **Generated file** | `tests/framework/test_vendor_argv_sweep.py` |
| **Description** | #1364 mechanical reintroduction check for the content-into-argv (E2BIG) bug class |
| **Date** | 2026-09-23 |
| **Model** | claude-opus-5 |
| **Risk level** | HIGH (diff_size tier floor; composite 0.3123 = MEDIUM) |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Issue #1364 (sweep: audit all CLI invocations for content-into-argv (E2BIG))
lists five acceptance criteria. A prior cycle's recovered working-tree diff
migrated eight scripts onto scripts/oversight/lib/vendor_invoke.sh, satisfying
criteria 1-3 and 5. Criterion 4 is unmet:

  "A mechanical check exists that would catch a reintroduction."

Write that check as a pytest module at tests/framework/test_vendor_argv_sweep.py.

Context the check must respect:
 - vendor_invoke.sh's own D-2 runtime guard already makes reintroduction
   impossible THROUGH that function. The gap this closes is a NEW call site
   that bypasses vendor_invoke entirely and writes `agy -p "$PROMPT"` again.
 - #1364's core insight: this bug class arms itself through unrelated content
   growth, so a one-time sweep cannot prevent recurrence. The check is the
   durable half.
 - Follow tests/framework/test_agent_invocation_migration.py T4.1's established
   conventions: scan CODE lines only (comments/docs legitimately name the old
   constructs), and hold exemptions in an explicit set asserted for equality so
   the assertion tightens automatically as slices land.
```

## Constraints Specified

- **Language/runtime:** Python 3, pytest; repo venv at `scripts/oversight/.venv/`.
- **Scan scope:** `scripts/`, `bootstrap/`, `bin/` — shell files only.
- **Must NOT** flag the correct, migrated form (`vendor_invoke agy "$TIMEOUT" ...`),
  where `agy` is an argument naming the vendor rather than the binary launched.
- **Must NOT** flag ordinary `VAR="$(cat f)"` assignments — the bug is file
  contents passed *as an argv element to a CLI*, not read into a variable.
- **Must** fire on the exact constructs #1364 removed, asserted explicitly, so
  the check cannot silently degrade into a vacuous always-PASS.
- **Exemption:** `scripts/oversight/lib/vendor_invoke.sh` — the primitive that
  replaces these constructs necessarily contains their vocabulary.

## Refinement History

**v1 — both patterns too loose; caught by the module's own guard test.**

- `_VENDOR_ARGV_PATTERN` matched the vendor name anywhere on the line, so it
  flagged `vendor_invoke agy "$AI_REVIEW_TIMEOUT" ...` — the *correct* migrated
  form — across all eight just-fixed scripts. The check would have blocked the
  very migration it exists to enforce.
- `_CAT_INTO_ARGV_PATTERN` matched any `"$(cat ...)"`, flagging nine ordinary
  variable assignments in unrelated files (`bin/hos-cron`, `post_review_thread.sh`,
  `branch_ownership.sh`, …).

**vFinal — anchor both patterns to argument position.**

- Vendor pattern now requires the CLI at *command position* (line start, `$(`,
  `|`, `;`, `` ` ``, `then`/`do`/`else`) and requires a prompt flag/subcommand
  before the runtime-expanded element.
- `cat` pattern now requires a preceding flag or `exec` token, so it means
  "passed as an argument" rather than "read into a variable".

The `test_the_sweep_would_actually_catch_a_reintroduction` guard test was
written *first* and is what caught v1's false positives. It asserts both
directions (fires on the removed constructs, silent on the migrated ones) —
without it, tightening the patterns could have quietly produced a check that
matches nothing and reports PASS forever.

**Verification that it is non-vacuous:** the patterns were run against
`git show HEAD:scripts/framework/validate_docs.sh` (pre-fix) and correctly
flagged `result=$(agy -p "$(cat "$tmpfile")" 2>/dev/null)`; the scan traverses
91 files.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

**For the reviewer's attention — known residual, deliberately out of scope:**
`scripts/run_panel.sh` lines 179-180 still pass the prompt to `claude -p` on
argv (the haiku/sonnet panel seats). That is the same bug class, left in place
because ADR-1643 AD-16 / TD §6.4 route those seats through
`bootstrap/invoke_agent.sh` at slice **W4b**, and `run_panel.sh` is a recorded
AD-16 exemption until then (pinned in `test_agent_invocation_migration.py`
T4.1's exemption set). This sweep covers the `agy`/`codex` vendor CLIs only.

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `tests/framework/test_vendor_argv_sweep.py`
4. Note any drift in a new version artifact (`test_vendor_argv_sweep.v1.md`)

---

## Revision 2 — review iteration (2026-09-23)

**Trigger:** overseer review of PR #1830 (comment 2026-09-23T09:41:38Z) returned
REQUEST CHANGES with two findings; human review (`ScottThurlow`,
CHANGES_REQUESTED) directed: "Please make changes requested by overseer".

**Finding 1 — lint.** The new file was the sole *in-scope* cause of a red
`oversight-gate-lint`: flake8 `E201`/`E202` ×4 on the
`f"... { {k: hits[k] for k in sorted(...)} }"` construct (the spaces are
load-bearing — without them `{{` is an f-string brace escape), plus black
wanting the `hits.setdefault(...).append(...)` calls on one line.

**Finding 2 — pattern evasion.** The overseer ran `_VENDOR_ARGV_PATTERN`
directly and found five forms that MISS but must MATCH, from two causes:
a literal prefix before the expansion (`agy -p "Review this: $CODE"` — the
*more* natural way a fresh call site gets written, and squarely in the E2BIG
class), and an incomplete command-position alternation (missing `if`, `while`,
`until`, `!`, `time`). `_CAT_INTO_ARGV_PATTERN` had the same literal-prefix gap.

**Prompt issued for the fix:**

```
Fix both findings in tests/framework/test_vendor_argv_sweep.py ONLY.

1. Lint: hoist the dict comprehension into a local before the f-string and
   interpolate the plain name (do NOT just delete the load-bearing spaces);
   collapse the two setdefault().append() calls to one line.
2. Widen the argv-element clause from "argument BEGINS with an expansion"
   to "quoted argument CONTAINS an expansion anywhere":
   "?\$(?:\(|\{|[A-Za-z_])  ->  (?:"[^"]*)?\$(?:\(|\{|[A-Za-z_])
   Apply the same widening to _CAT_INTO_ARGV_PATTERN's "\$\(\s*cat\b tail.
3. Add if/while/until/time as \b-anchored keyword alternatives and `!` to the
   [|&;`(] class in the command-position prefix.
4. Pin all seven new forms in `reintroductions`, and add a literal-prefix
   assertion for _CAT_INTO_ARGV_PATTERN.

CRITICAL: the `migrated` list must still NOT match after the widening — that
list is the whole reason the command-position anchor exists. If the widened
pattern false-positives on any of it, the widening is wrong.
```

**Verification of this revision (both directions, re-run independently of the
implementing agent):** all ten must-match forms — including all five the
overseer reported as MISS — now match; all five must-not-match forms (the
migrated `vendor_invoke` shape, the `claude -p` stdin pipe, `codex exec <
"$tmpfile"`, and a docs mention) still miss. Full suite 3532 passed, 15 skipped.
`lint_check.sh` on this file alone: GATE PASS.

**Known residual, deliberately out of scope (overseer-scoped):** the changeset
gate still reports one black failure on `tests/oversight/test_red_team_fail_closed.py`.
Confirmed pre-existing — `black --check` fails on that file as it stands on
`origin/main`. Per the overseer, "not this PR's to fix" (#1571 item 4 territory);
this PR merely drags it into a changeset-scoped gate.
