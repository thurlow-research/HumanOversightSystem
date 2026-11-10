# Prompt Artifact — readopt.py / delete_branch.sh (#2298 delete-on-close residuals)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/github.py` (new `list_pulls_strict`), `scripts/automation/readopt.py` (`delete_head` steps 11/11b), `bootstrap/delete_branch.sh` (`_json_escape`), `tests/automation/test_readopt.py`, `tests/automation/test_delete_branch.py`, `tests/framework/test_consumer_framework_files.py` |
| **Description** | #2297 follow-ups: a 404 / empty-body / non-list open-PR lookup in `delete_head` is KEPT `pr-lookup-indeterminate`, never a delete; a consumer-ship-set check that `bootstrap/edit_issue.sh` never ships without `bootstrap/delete_branch.sh`, plus a sandbox-template allowlist test; `delete_branch.sh` audit JSON escapes C0 control characters so the event is always written |
| **Date** | 2026-11-10 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief (verbatim
except for whitespace):

```
You are implementing GitHub issue #2298 (items 1-3) in the HOS repo, on the already-checked-out
branch worker-2298-delete-on-close-residuals-261110042001-262776. Do NOT create, switch, stash
or check out branches. Do NOT edit .claude/agents/*.md (the orchestrator edits those). Do not
file issues, post comments or change labels.

ITEM 1 - an open-PR lookup that is not a genuine list must fail closed.
scripts/automation/readopt.py delete_head() steps 11 and 11b call
github.list_pulls(owner, name, head=..., state="open") and list_pulls(..., state="open", base=b).
scripts/automation/lib/github.py list_pulls() maps a None from _run_gh (HTTP 404, or an empty
body) to [] and wraps a dict payload into [dict]. So an indeterminate lookup reads as "no other
open PR" and the head is deleted.
Required:
 a. Add github.list_pulls_strict(owner, repo, head=None, state="all", base=None) ->
    Optional[list]. Same request as list_pulls (factor the URL building into one private helper
    both use - do not duplicate it). Return the list when _run_gh returns a list; return None
    when _run_gh returns None or any non-list payload. Do NOT change list_pulls' behaviour (it
    has other callers).
 b. delete_head's default open_pulls_for / open_pulls_based_on lambdas use list_pulls_strict.
    After each call: if the result is not a list -> kept("pr-lookup-indeterminate") (exit 3,
    nothing deleted). Exceptions keep their existing ERROR path. A genuine [] keeps today's
    behaviour.
 c. Update the module/function docstring and the step table rows 11/11b in
    docs/v0.7.0/TECHNICAL-DESIGN-2288-S2-delete-on-close.md to name the new KEPT reason (one
    clause each, mark "[#2298]").
 d. Tests in tests/automation/test_readopt.py next to the existing delete_head tests: seam
    returning None for open_pulls_for -> KEPT pr-lookup-indeterminate and remote_delete never
    called; same for open_pulls_based_on; a dict payload -> same; [] -> deletes as before. Plus
    unit tests for list_pulls_strict (patch github._run_gh: None -> None, {} -> None, [] -> [],
    [x] -> [x]) in the existing github lib test file.

ITEM 2 - ship-together check.
bootstrap/edit_issue.sh --state closed on a PR runs bootstrap/delete_branch.sh; without it every
PR close exits 4. Add to tests/framework/test_consumer_framework_files.py a test that fails if
bootstrap/edit_issue.sh is in the consumer list (scripts/framework/framework_consumer_files.txt)
without bootstrap/delete_branch.sh. Write it data-driven (a small dict {dependent: [required]})
and also a test of the helper that a synthetic list containing edit_issue.sh only is rejected.
Also add a test (same file or a sandbox-template test if one exists - search tests/ for
sandbox-policy.template.json) asserting contract/sandbox-policy.template.json's allow list has a
Bash rule matching "bash bootstrap/delete_branch.sh --pr 1 --app worker" (the existing rule is
"Bash(bash bootstrap/*)"; match with fnmatch on the inner pattern). Do not edit the list file
or the template.

ITEM 3 - delete_branch.sh audit JSON.
bootstrap/delete_branch.sh _json_escape escapes only backslash and double quote, so a C0 control
character (e.g. a newline or ESC inside an ERROR reason) yields invalid JSON and audit_write_event
drops the event. Make _json_escape produce valid JSON for any input: escape \n \r \t as \n \r \t
and every other byte 0x01-0x1f (and 0x7f) as \u00XX. Pure bash, no subprocess per character is
fine but keep it simple and readable; no new dependencies. Test in the existing delete_branch.sh
test file (search tests/ for delete_branch): feed a result line whose reason contains a newline-free
ESC and a tab (the result line is one line) and assert the audit event file is written and parses
as JSON with the original characters round-tripped. Follow the existing test's stubbing pattern.

Process: run the touched test files with scripts/oversight/.venv/bin/python -m pytest, then
bash scripts/oversight/run_gates.sh on the changed files, fix black/flake8/shellcheck findings,
then commit (one or more commits) with this exact trailer block after one blank line:

Prompt-Artifact: prompts/scripts/automation/readopt.v2298.md
AI-Model: claude-opus-5-5
AI-Risk: MEDIUM
Supervised-by: ScottThurlow

Commit subject prefix "fix(2298): ". Do not mention closing keywords for any issue. Report the
self-flag (RISK/CONFIDENCE/BLAST RADIUS) per AGENTS.md, the commit SHAs, and the test results.
```
