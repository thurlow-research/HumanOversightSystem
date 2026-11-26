# Prompt Artifact — docs/CRON-SETUP.md (#2396 overseer branch-reap enable procedure)

| Field | Value |
|---|---|
| **Generated file** | `docs/CRON-SETUP.md` (§"Overseer branch hygiene"), `tests/automation/test_hos_cron.py` (`TestOverseerBranchHygiene`) |
| **Description** | Make the documented reap-enable procedure executable as written: the attended first real run is the engine command TD-2287 §6.4 specifies (not a suspended `bin/hos-cron` run, which exits at the suspend check before the reap); document the 24 h stamp and the overseer early exits that skip the reap; pin both with tests (#2396, follow-up of #2287) |
| **Date** | 2026-11-20 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM (test code; docs) |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with the brief below (docs fix
plus tests, no separate design chain: the issue's "Required" section plus the binding
TD-2287 §6.1/§6.2/§6.4 are the spec).

```
Fix #2396 on the current branch. Do NOT switch branches, stash, checkout, reset or rebase.
Do NOT edit bin/hos-cron, scripts/, .claude/agents/ or CLAUDE.md. Two files only:
docs/CRON-SETUP.md and tests/automation/test_hos_cron.py.

Facts (verified by the worker against main 15972e8a2):
- bin/hos-cron's project-suspension check (≈line 271-292) `exit 0`s before the overlap lock,
  so a manual `bin/hos-cron --role overseer` run on a suspended project never reaches the
  overseer reap block (≈line 1816). The current enable step (2) in docs/CRON-SETUP.md
  §"Overseer branch hygiene" ("hos-suspend the project ..., set HOS_OVERSEER_BRANCH_REAP=on
  for a single manual run") therefore cannot work.
- Unsuspended, the reap is also skipped when (a) the 24 h stamp
  `$_HOS_DIR/branch-reap/overseer-<project>.last` is younger than 24 h. The stamp is written
  after EVERY non-off attempt (dry-run included, failures included; TD-2287 §6.2), so a
  manual `on` run within 24 h of a scheduled dry run is skipped. (b) the overseer cycle
  exits earlier: no open PRs, all open PRs draft/conflicting, open-PR fetch failure, hos-halt,
  halt check unavailable, usage pause, preflight/auth failure (TD-2287 §6.1 accepts this:
  "Cycles that exit early with no actionable PRs do not run it").
- TD-2287 §6.4 (binding architect edit A2) specifies the attended first real run as the
  engine command itself, run by a human in their own terminal, never an agent session:
    python3 -m scripts.automation.readopt --repo <Overseer clone> reap-orphans --local-only --max-deletions 100
  from a main checkout, reviewing its REAPED lines against the reviewed dry run.
- That direct run writes NO cycle-branch-reap audit events (only bin/hos-cron's block writes
  them). Its recovery handles are its own output: each REAPED line's tip=<sha> (and pr=#N:
  refs/pull/N/head), plus the ARCHIVED line / refs/archive/reap/<branch>@<tip12> ref written
  before any unlanded delete (#2314). Recovery: `git branch <name> <tip>` or
  `git branch <name> refs/archive/reap/<name>@<tip12>`.

A. docs/CRON-SETUP.md §"Overseer branch hygiene":
   1. Replace the "**Enable procedure.**" paragraph. Keep step (1) (review the dry run).
      Step (2): the attended real run is the TD-2287 §6.4 engine command above, run by a
      human from their own terminal (never an agent session), in the Overseer clone on an
      up-to-date main. Suspending the project (`hos-suspend --project <p>`) first is still
      advised so no scheduled overseer cycle runs alongside it — the direct command does not
      read the suspend marker, so suspension no longer blocks it. Tell the operator to save
      the output (e.g. `... 2>&1 | tee <file>`) because this run writes no audit events, and
      say what the recovery handles are (tip=, pr=, ARCHIVED ref) and the one-line recovery.
      Compare REAPED against the dry run's WOULD-REAP set. Then `hos-suspend --project <p>
      --clear`. Step (3) unchanged in substance: only then set
      `<project>_overseer_branch_reap=on`; the first audited deleting run is the next
      scheduled overseer cycle that reaches the reap (see the cadence note), verifiable from
      its `cycle-branch-reap` / `cycle-branch-reap-summary` events.
      Say explicitly, in one sentence, why a manual `bin/hos-cron` run is NOT the attended
      run: it exits at the suspend check when suspended, and when not suspended it is skipped
      by a fresh stamp or an early exit.
   2. Add a short cadence note (paragraph, before the Enable procedure) documenting: the
      stamp path `branch-reap/overseer-<project>.last` under the HOS state dir; it is written
      after every dry-run or on attempt, including failures; the reap runs only on an
      overseer cycle that gets that far, so suspended, halted, usage-paused, preflight/auth
      failed and no-open/no-actionable-PR cycles skip it (and do not stamp); deleting the
      stamp makes the next qualifying cycle re-run it.
   Keep the existing prose style (short sentences, backticks for paths/commands). Do not
   touch the audit-event tables or the archive notes.

B. tests/automation/test_hos_cron.py, class TestOverseerBranchHygiene (reuse self._stubs,
   self._run, self._invocations, self.stamp and cron.suspend_file(); follow the existing
   suspend-marker pattern at ≈line 3087). Add:
   1. suspended project + HOS_OVERSEER_BRANCH_REAP=on → rc 0, "[SUSPENDED]" in stdout,
      readopt never invoked, no stamp written.
   2. no open PRs (HOS_TEST_OPEN_PR_NUMS="" — confirm how the fixture expresses "no open
      PRs"; read it, do not guess) + mode on → readopt never invoked, no stamp.
   3. shared stamp: a default (dry-run) run stamps; a following run with
      HOS_OVERSEER_BRANCH_REAP=on inside 24 h does not invoke readopt; after the stamp is
      unlinked, the on run invokes `reap-orphans --local-only --max-deletions 100`.
   4. doc test: read docs/CRON-SETUP.md, isolate the "**Enable procedure.**" paragraph
      (from that marker to the next blank line), and assert it contains
      `reap-orphans --local-only --max-deletions 100`, names the stamp
      `overseer-<project>.last` somewhere in the section, and does NOT contain
      `HOS_OVERSEER_BRANCH_REAP=on` (the broken manual-hos-cron instruction). Anchor on the
      bold marker, not on a phrase that also appears elsewhere.
   Each test has a docstring citing #2396.

Run `scripts/oversight/.venv/bin/python -m pytest tests/automation/test_hos_cron.py -k
OverseerBranchHygiene -q` and make it green. Commit (one commit) with trailers, as one
contiguous block after a single blank line:

Prompt-Artifact: prompts/docs/CRON-SETUP.v2396.md
AI-Model: claude-opus-5-5
AI-Risk: MEDIUM
Supervised-by: ScottThurlow

Commit subject: `docs(#2396): executable overseer reap enable procedure; document 24h stamp`.
Do not use any closing keyword (closes/fixes/resolves #N) in the message. Report the SHA,
files changed, and test output. Self-flag RISK/CONFIDENCE/BLAST RADIUS per AGENTS.md.
```

---

## Revision: security-review round 1 follow-up

The worker re-dispatched the `coder` subagent for a docs-only change to the "**Enable procedure.**"
paragraph in `docs/CRON-SETUP.md`, on the security-reviewer's findings:

```
Edit only docs/CRON-SETUP.md, in the "**Enable procedure.**" paragraph. Keep it one paragraph
(no blank line; test_h8 splits on "\n\n"), keep `reap-orphans --local-only --max-deletions 100`,
do not add `HOS_OVERSEER_BRANCH_REAP=on`, do not touch the 24 h stamp paragraph.
1. SHOULD_FIX: tell the operator to run `git fetch origin` in the Overseer clone first. The
   engine's base is remote-tracking origin/main (the `reap_orphans()` base default in
   scripts/automation/readopt.py, about L1211; reap-orphans exposes no `--base`), not local
   main. A stale origin/main only makes the reap more conservative.
2. NIT: refs/pull/N/head recovery needs `git fetch origin pull/N/head:refs/pull/N/head` first.
3. NIT: the `tee <file>` target must be outside the repo tree so the output is not committed.
```

## Revision: code-review round 2

Docs-only fix: the pull-ref recovery sentence in `docs/CRON-SETUP.md` now gives the refspec
`git fetch origin pull/N/head:refs/pull/N/head` (a bare `git fetch origin pull/N/head` does not
create a local `refs/pull/N/head`), and the round-1 follow-up items above are corrected to match.

## Revision: second-review round 1

Docs-only fix to the "**Enable procedure.**" paragraph in `docs/CRON-SETUP.md` on agy findings: (1) added that
the command, like the scheduled reap, needs `scripts/automation/readopt.py` in the Overseer clone, which today
is only the HOS repo clone (`scripts/automation/` is not shipped to consumers), so in a consumer project the
reap is skipped silently (hos-cron guards the block on the file's existence; no log line or audit event); (2) the `tee` target
is now a persistent file outside the clone (`~/reap-<project>-<date>.log`) instead of `$TMPDIR`.

## Revision: code-review round 4

Docs-only fix: the consumer-project claim in `docs/CRON-SETUP.md` is corrected; hos-cron skips the overseer reap silently when `scripts/automation/readopt.py` is absent.
