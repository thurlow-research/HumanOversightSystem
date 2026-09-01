# ADR-1415 — Worktree hygiene: quarantine-then-verify-then-revert, opt-in, cycle-start only

**Status:** ACCEPTED — implemented.
**Date:** 2026-09-01
**Author:** worker (autonomous, recovering and completing debris from an earlier dead cycle — see §4)
**Issue:** #1415 · **Milestone:** v0.7.0 · **Risk tier: MEDIUM** (touches `bin/hos-cron`, a protected surface — `bin/**` in `scripts/framework/protected_surfaces.txt` — human review required regardless of tier)

## 1. Problem

`#1415` (companion to `#1414`): a cycle that dies mid-chain can leave debris —
untracked scratch files, uncommitted edits to tracked files — in the worktree.
The cycle-start baseline (`tests/framework/test_scripts_index.py` and others)
fails on that debris and halts every *subsequent* cycle until a human notices
and manually cleans the tree, even though the debris has nothing to do with
the code those later cycles would otherwise build. Measured cost in the
originating incident: ~40 minutes, 4 wasted cycles, zero self-recovery
(`#1413`).

## 2. Decision

A pre-baseline sweep, `_worktree_hygiene()` in `bin/hos-cron`, runs immediately
after `git fetch` and before the `#1044` return-to-main check and the `#1393`
ff-only merge guard (both of which a dirty tree defeats). It is **opt-in**
(`<project>_worktree_hygiene=preserve` in `projects.conf`, or
`HOS_WORKTREE_HYGIENE=preserve`; default `off`, a total no-op) and
**worker-only**.

When enabled, on a dirty tree it:

1. Refuses (leaves the tree untouched) if a git operation is already
   in-progress (merge/rebase/cherry-pick) or unmerged paths exist — that is
   judgment territory, not mechanical debris.
2. Computes the total byte size of the diff and refuses above a ceiling
   (default 256 MiB, `HOS_WORKTREE_HYGIENE_MAX_BYTES`) — an unbounded copy is
   its own failure mode.
3. Copies every untracked path and a binary patch of every tracked-file
   uncommitted change into a timestamped quarantine directory under
   `$HOS_STATE_DIR/worktree-quarantine/`, with a `MANIFEST.txt` (path, git
   status code, and — for untracked files — a symlink/permission-bits note)
   and a `RESTORE.md` with copy-pasteable recovery commands.
4. **Verifies the quarantine byte-for-byte** — patch reverse-applies cleanly,
   every untracked file's size matches its copy, and the copy count matches
   the enumerated count — before removing anything.
5. Only then reverts tracked files to `HEAD` and deletes untracked ones, then
   re-checks `git status` is clean; any residual dirty path is reported as a
   `failed` result rather than silently declared success.
6. Emits an audit event (`cycle-worktree-hygiene` or
   `cycle-worktree-hygiene-fail`) naming exactly what was swept or why it
   refused — never a bare "cleaned the tree" with no detail.

The cycle-start broken-state escalation (the `needs-human,needs-ai` issue
`bin/hos-cron` files when the baseline is red) is annotated with one of two
notes: if hygiene ran and the tree was verified clean before the baseline
still failed, the note says so explicitly — **this is genuine breakage, not
debris**. If hygiene itself failed, the note says the red baseline may be a
*consequence* of the leftover debris, not the code, and points the human at
`git status` before assuming otherwise. When hygiene is disabled (the
default), the escalation body is byte-identical to the pre-#1415 text — this
ADR changes nothing for a project that hasn't opted in.

## 3. Why quarantine-then-verify-then-revert, and why opt-in by default

Nothing is ever deleted before it is copied elsewhere and verified. This is
deliberately more conservative than a `git stash` or `git clean -fd`: no git
ref or stash entry is created or consumed (so it cannot collide with or be
confused for a human's own stash), and the verification step exists
specifically so that a copy failure is caught *before* the only surviving
version of the debris is destroyed.

The feature defaults to **off**, requiring explicit opt-in, for a concrete
reason recorded in §4 below — not merely as generic caution.

## 4. Incident: an earlier, less careful draft of this exact mechanism destroyed work

During the same day this issue was worked, a cycle (`worker-hos-260901213001-3271241`,
2026-09-01T21:30:44Z) ran an earlier, in-progress draft of worktree hygiene —
present only as an uncommitted edit to `bin/hos-cron` at the time, inherited
from a prior cycle's dirty tree, evidently enabled via a one-off
`HOS_WORKTREE_HYGIENE` value for live testing. Its own audit record:

```json
{"event":"cycle-baseline-hygiene-recovered","quarantine_dir":"/home/scott/.hos/quarantine/worker-hos/worker-hos-260901213001-3271241","quarantined_count":1,"quarantined_paths":"audit/log/2026/09/","reverted_count":3,"reverted_paths":"DECISIONS.md,bin/hos-cron,tests/automation/test_hos_cron.py","role":"worker","timestamp":"2026-09-01T21:30:44Z"}
```

Only the untracked `audit/log/2026/09/` directory was quarantined. The three
**tracked** files it "reverted" — `DECISIONS.md`, `bin/hos-cron`, and
`tests/automation/test_hos_cron.py` — were checked out to `HEAD` with **no
patch saved first**. Those three files held what was, by the file list, a
*more complete* implementation of this same feature: code, a test suite, and
a decision-log entry. None of it was recoverable — no patch existed to
restore from, and the content was never committed, so no git object holds it
either. The mechanism that ran destroyed a more complete version of itself,
with no safety net, while under live test.

This is not a hypothetical risk the design below guards against defensively —
it is the reason the design below has a verify-before-remove step at all. The
implementation this ADR describes always writes `tracked.patch` (via `git
diff --binary HEAD`) and confirms it reverse-applies before touching anything,
which is exactly the safeguard that draft lacked. The default stays `off`
until a project operator has reviewed this ADR and chosen to opt in with that
history in view; this is a deliberate, not merely cautious, choice.

## 5. Out of scope (tracked separately)

`#1415`'s acceptance criteria also call for (a) bounding retry cost so
repeated identical baseline failures don't re-run the full suite indefinitely,
and (b) reaping stranded zero-commit local branches. Neither is addressed by
this mechanism — both are a different shape of fix (loop-level backoff;
branch lifecycle, not worktree contents) and are tracked in **#1498** rather
than bundled into this PR's `bin/**` diff.

## 6. Scope

`bin/hos-cron` (`_worktree_hygiene()` + call site + broken-state escalation
annotation + header docs), `tests/automation/test_hos_cron.py`, this ADR,
`DECISIONS.md`.
