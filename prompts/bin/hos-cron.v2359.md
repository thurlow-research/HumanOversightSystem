# Prompt Artifact — bin/hos-cron (#2359 run each role on its agent file's model)

| Field | Value |
|---|---|
| **Generated file** | `bin/hos-cron` (per-role `--model` resolution + `cycle-model` audit), `bootstrap/lib/agent_model.py` (new, stdlib-only frontmatter `model:` reader), `tests/automation/test_hos_cron.py`, `tests/automation/test_agent_model.py` (new), `docs/COST-MANAGEMENT.md` |
| **Description** | The top-level cron cycle ignores the role agent file's `model:` frontmatter (it only applies to subagent dispatch). hos-cron now reads `model:` from `.claude/agents/<role>.md`, passes `--model <m>` to claude, logs/audits the model, and fails closed when it cannot be read (#2359 re-scope, 2026-11-16). |
| **Date** | 2026-11-16 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (protected surface `bin/**`, `bootstrap/**`) |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief:

```
Issue #2359 (re-scoped by the human 2026-11-16). bin/hos-cron launches each cycle as a top-level
`claude --print --permission-mode bypassPermissions` (bin/hos-cron ~line 2318, `_claude_cmd`).
The `model:` frontmatter in .claude/agents/worker.md / overseer.md applies only when the file is
invoked as a subagent, so the cycle runs on the account default model. Fix:

1. New stdlib-only helper bootstrap/lib/agent_model.py (invoked as `python3 -I <path>`, same
   pattern as bootstrap/lib/hos_tmp_root.py; system python, no PyYAML). CLI:
     agent_model.py resolve --agent-file <path>
   prints the `model:` value of the file's YAML frontmatter (block delimited by a first line
   `---` and the next `---` line; top-level `model:` key only; strip surrounding quotes and
   whitespace; ignore trailing `# comment`). Exit non-zero with a one-line stderr message that
   names the file for: missing/unreadable file, no frontmatter, no `model:` key, empty value,
   or a value that fails `^[A-Za-z0-9][A-Za-z0-9._:\[\]-]*$` (argv-safety). Never prints a
   default.
2. bin/hos-cron: where `_claude_cmd` is built, resolve the model from
   "$REPO_ROOT/.claude/agents/${ROLE}.md". On failure: echo "$LOG_PREFIX ERROR: ..." naming the
   file, `_audit cycle-model-unresolved "role=... file=..."`, and exit non-zero BEFORE claude is
   invoked (fail closed — never fall back to the default model). On success: append
   `--model "$m"` to `_claude_cmd`, echo "$LOG_PREFIX model=$m (from .claude/agents/$ROLE.md)",
   and `_audit cycle-model "role=$ROLE model=$m source=.claude/agents/$ROLE.md"`. No second copy
   of the setting anywhere (no env/config override).
3. Tests: tests/automation/test_agent_model.py (unit: happy path, quotes, comment, missing file,
   no frontmatter, no key, empty, unsafe value, model key nested/indented is not read).
   tests/automation/test_hos_cron.py: the fake repo must now carry worker.md / overseer.md with
   `model:` frontmatter and bootstrap/lib/agent_model.py in its copy list, so existing tests
   still pass; add tests proving the claude stub's argv contains `--model <m>` taken from the
   agent file for BOTH roles (use distinct values, e.g. opus for worker, sonnet for overseer, to
   prove the per-role file is read), and that a missing/model-less agent file fails closed with
   claude never invoked.
4. docs/COST-MANAGEMENT.md: record that hos-cron now passes `--model` from the role agent file
   (before #2359 the overseer/worker cron cycles silently ran the account default despite
   `model: opus`), that worker, overseer and oversight-evaluator run on Opus permanently per
   the human's 2026-11-16 ruling, and that this is to be revisited after the v0.7.2
   deterministic-orchestration work (#1643/#1644).
Do not edit .claude/agents/** (worker.md and overseer.md already say `model: opus`).
Tests must clean up their own temp. Commit with "Part of #2359" and the trailer block below.
```

Trailer block given to coder:

```
Prompt-Artifact: prompts/bin/hos-cron.v2359.md
AI-Model: claude-opus-5-5
AI-Risk: HIGH
Supervised-by: ScottThurlow
```

## Addendum — iteration 2 (2026-11-16)

Behaviour added after the original brief:

- Model resolution moved before the token mint, immediately after `_audit` is defined, so a bad
  role file fails before any per-cycle work (lock held, EXIT trap frees it, no in-progress label).
- Fail-closed exit code is 78 (EX_CONFIG).
- The helper's one-line reason is surfaced in the log, sanitised (control bytes stripped, 600 chars).
- `model: inherit` and duplicate top-level `model:` keys are rejected by the resolver.
- Iteration 2 items: (1) `bootstrap/lib/agent_model.py` added to
  `scripts/framework/framework_consumer_files.txt` (installed hos-cron calls it unconditionally),
  with a guard test that every `bootstrap/lib/*.py` hos-cron invokes is in that list;
  (2) the helper is captured stdout-only (`2>/dev/null`) on success, the reason re-derived from
  stderr on failure, and the captured value must match `^[A-Za-z0-9][A-Za-z0-9._:\[\]-]*$`
  (single line) or the cycle fails closed (exit 78, `cycle-model-unresolved`).
