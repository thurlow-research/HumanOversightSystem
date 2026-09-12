# Prompt Artifact — hos-cron

| Field | Value |
|---|---|
| **Generated file** | `bin/hos-cron` |
| **Description** | Correct #1265 framing: nested hos-cron processes are a benign ps/bash pipeline-subshell artifact, not a lock failure |
| **Date** | 2026-09-12 |
| **Model** | claude-sonnet-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Investigation summary handed to the `coder` agent (autonomous worker session, picking up #1265 from the v0.7.0 candidate list):

```
Issue #1265 reported two same-role hos-cron processes for (worker, hos) alive
at once, one nested as a child of the other. I (the worker session)
reproduced this LIVE on the host during my own cron cycle: `ps -eo
pid,ppid,pgid,sid,lstart,cmd` showed my own top-level `bash bin/hos-cron
--role worker --project hos` process with a CHILD bearing the IDENTICAL
command line, itself parenting `timeout 1800 claude --print ...` -> `claude
--print ...` (me). I then wrote a minimal isolated /tmp reproduction using a
two-function bash pipeline (`f1 | f2`) and confirmed via `ps` that the
right-hand side of a pipe running a shell FUNCTION (not an external binary)
is forked without execve(), so it retains the parent script's exact argv in
ps/pstree output.

Root cause: bin/hos-cron's `_build_prompt | _run_claude` pipeline puts
`_run_claude` (a shell function) on the right of `|`. This is the same
mechanism, not a lock failure — the overlap lock is acquired once, earlier
in the script, and never re-acquired by the pipeline subshell.

Implement:
1. A comment in bin/hos-cron above the `_build_prompt | _run_claude`
   invocation explaining this mechanism, referencing #1265.
2. In tests/automation/test_hos_cron.py: correct the existing
   TestOverlapLock test's comment (it currently claims to reproduce #1265's
   observation via real independent-process contention, which it does not —
   that test covers a different, real thing: genuine #1002-style lock
   racing). Add a NEW test that pins the actual #1265 shape via /proc
   inspection (PPID + byte-identical cmdline match) using the existing
   started/release blocking-claude-stub pattern.
3. A DECISIONS.md entry recording the finding, both verification methods,
   and the corrected test attribution.

Constraints: documentation/test-only, no behavior change to bin/hos-cron's
logic; do not touch .claude/agents/**; run TestOverlapLock repeatedly to
confirm no flakiness.
```

Full multi-paragraph technical detail (bash pipeline fork semantics, exact process trees observed, exact file/line targets) was given verbatim in the actual agent dispatch — condensed here for artifact brevity; the working tree diff is the ground truth for what was actually implemented.

## Constraints Specified

- Documentation/comment and test-only change — no behavior change to `bin/hos-cron`'s lock acquisition, pipeline structure, or any other logic.
- Do not touch `.claude/agents/**`.
- New test must reuse the existing `cron`/`tmp_path` fixtures and `_write_exec` helper, and must not leak a hung subprocess on assertion failure (matching the sibling test's `finally` cleanup pattern).
- Verify no flakiness: run the new test and its class repeatedly before reporting done.

## Refinement History

v1 (coder's first pass): added the `bin/hos-cron` comment, corrected the existing test's comment, added the new `/proc`-inspection test, and the `DECISIONS.md` entry. Passed all tests, but code review (`code-reviewer` agent) found the `DECISIONS.md` entry's claim that three pre-existing `#1265` citations in the branch-reaper section (lines ~1271, 1308, 1346) were "a different concern... tied to #1002" was inaccurate — those comments actually still cited `#1265` itself as proof that "two same-role cron processes can overlap," directly contradicting this change's own headline finding.

vFinal (top-level worker session, post-review): re-pointed all three branch-reaper citations from `#1265` to `#1002` (the real mechanism — a stale-lock reclaim can genuinely leave two same-role processes alive, unlike #1265's benign pipeline-subshell artifact), corrected the `DECISIONS.md` scope paragraph to match, and tightened one test comment (the `argv` shown in the new test's docstring is absolute-path, not the shorthand `bash bin/hos-cron --role worker --project hos` used for readability elsewhere).

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->
Internal `code-reviewer` agent pass: CHANGES_REQUESTED (the branch-reaper mis-citation above), fixed before this commit. Pending human/overseer review as usual for this pipeline.

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `bin/hos-cron`
4. Note any drift in a new version artifact (`hos-cron.v1.md`)
