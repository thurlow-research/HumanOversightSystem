# Prompt Artifact — overseer_second_review.py / run_second_review.sh --authority (#2357 S1a)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/overseer_second_review.py` (new), `scripts/run_second_review.sh` (`--authority` mode), `scripts/automation/lib/merge_authority.py` (`keyed_flock` extracted from `_bounce_lock`), `tests/automation/test_overseer_second_review.py` (new), `SCRIPTS-INDEX.md` (regenerated) |
| **Description** | Slice S1a of #2357: the overseer's own authority-mode cross-vendor second-review runner, its overseer-owned per-head record/cache with locking and atomic completion, and the reusable keyed lock. Inert — nothing calls it until S1b. |
| **Date** | 2026-11-16 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief (verbatim
except for whitespace and the Worker clone's absolute path, redacted to `<worker-clone>`
for the portability gate):

```
You are implementing slice S1a of GitHub issue #2357 in the HOS repo at
<worker-clone>, on the already-checked-out branch
worker-2357-overseer-own-second-review-261116012001-2455441. Do NOT create, switch,
stash, check out or reset branches. Do NOT edit .claude/agents/*.md, docs/, or the
prompt artifact. Do not file issues, post comments or change labels.

The binding design is docs/v0.7.0/TD-2357-S1a-overseer-second-review-runner.md
(architect-APPROVED, amendments A1-A8 included), under
docs/v0.7.0/ADR-2357-overseer-second-review.md. Read both in full before writing code.
Implement exactly what the TD specifies — no more, no less. If anything in the TD is
ambiguous or contradicts the code, stop and report the question rather than guessing.

Files you may touch (TD file list):
  1. scripts/run_second_review.sh            (add --authority mode; worker mode unchanged)
  2. scripts/automation/lib/overseer_second_review.py   (new)
  3. scripts/automation/lib/merge_authority.py           (keyed_flock extraction only;
                                                          _bounce_lock behaviour identical)
  4. tests/automation/test_overseer_second_review.py     (new; every numbered test in the TD)
  5. SCRIPTS-INDEX.md  (regenerate: bash scripts/framework/gen_scripts_index.sh — no --check)

Hard constraints:
- S1a is inert: nothing existing calls the new module. The worker's existing
  run_second_review.sh invocation (without --authority) must behave exactly as today.
- Tests inject runner/worktree/git; stub gh and vendor CLIs on PATH; no live vendor or
  network calls; all temp files under pytest tmp_path (the suite fails on leaked temp).
- Vendor text is untrusted data: sanitise per TD §6.2.
- Use scripts/oversight/.venv/bin/python for pytest/black/ruff.

When done:
- Run the TD's test command list plus: bash scripts/framework/run_tests_inner_loop.sh
- Run bash scripts/oversight/run_gates.sh on the changed files and fix every finding in
  touched files (including black formatting).
- Commit with this trailer block (one contiguous block, no blank lines inside it):

    Prompt-Artifact: prompts/scripts/automation/lib/overseer_second_review.v2357.md
    AI-Model: claude-opus-5-5
    AI-Risk: HIGH
    Supervised-by: ScottThurlow

    Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

- Report: files changed, test results (counts), gate results, and self-flag per
  AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS).
```
