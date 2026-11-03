# Prompt Artifact — hos-cron

| Field | Value |
|---|---|
| **Generated file** | `bin/hos-cron` (also `tests/automation/test_hos_cron.py`) |
| **Description** | #1666: reclaim the overlap lock left by a holder that died across a reboot, using a `boot_id` stamp plus a boot-time check only for pid-less locks |
| **Date** | 2026-10-13 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (raised from MEDIUM by risk-assessor) |
| **Human review status** | ⬜ Pending |

---

## Prompt

The autonomous worker session took #1666 from the v0.7.0 candidate list. It got a binding architect ruling (summarised under Constraints below), then gave the `coder` agent this prompt (abridged — the path and branch boilerplate is dropped):

```
Problem: bin/hos-cron (overlap lock, ~lines 294-338) — after a reboot
interrupts lock acquisition (mkdir done, pid never written), every cron fire
exits "another hos-cron ... run is acquiring the lock" until the age ceiling
(now 6h).

The binding design is in .claudetmp/1666/architect-ruling.md — read it and
implement EXACTLY that (boot_id written before pid; steps 0a/0b before the
age-ceiling check; _stat_mtime positive-integer guard; fail-safe skips; Linux
/proc/stat btime + macOS `sysctl -n kern.boottime` sec= parsing; NO env
override; no clock-based reclaim for any lock that has a pid). Update the
comment block above the lock (the (a)/(b) list) to describe the new (c)
reboot-staleness path and cite #1666. Keep the diff minimal.

Tests: add the six cases from the ruling to tests/automation/test_hos_cron.py
in the existing "Overlap lock" section, using the existing `cron` fixture.
Linux-only cases should skip cleanly when /proc/sys/kernel/random/boot_id or
/proc/stat are absent. Then run the lock tests, the full inner loop, and
`bash -n bin/hos-cron`.
```

## Constraints Specified

These come from the architect ruling, which is binding:
- The holder writes `boot_id` (Linux `/proc/sys/kernel/random/boot_id`) before `pid`. If it can't be read, no empty file is written.
- Step 0a: if the lock has a `boot_id` and it differs from the current one, reclaim. If it matches, fall through to the existing checks.
- Step 0b: only for a lock with no `boot_id` and an empty pid, reclaim when the lock dir's mtime is earlier than the boot time, with a margin of 0.
- A lock that has a pid but no `boot_id` is never reclaimed on clock evidence. A clock step after boot would otherwise let a live lock be reclaimed.
- If any probe can't be read, its fast path is skipped. `_stat_mtime` returning `0` must not count as "predates boot".
- No environment override for boot time or `boot_id`.

## Refinement History

v1 (coder): implemented the ruling and added tests for ruling cases 1–6. The inner loop passed.

vFinal (coder, after code review): `code-reviewer` APPROVED with four SHOULD_FIX items, all applied:
- Wrapped the `boot_id` reads as `{ tr …; } 2>/dev/null`. A failed `<` redirect printed to stderr even with `2>/dev/null`.
- The lock-side `boot_id` is now validated, and an invalid value counts as no `boot_id`.
- Renamed a test whose name claimed it checked write order, which it doesn't.
- Added tests for two cases: a pid-less lock carrying the current `boot_id` must not take step 0b, and a pid-bearing lock with an invalid `boot_id` must not be reclaimed.

Left for a follow-up, not this change: the existing check-then-act race between `rm -rf` and `mkdir`, which all three reclaim paths share.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->
Internal `code-reviewer` pass: APPROVED with the SHOULD_FIX items above, all applied. Pending human/overseer review (bin/** is a protected surface).

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim, along with the architect ruling
3. Compare key logic paths against `bin/hos-cron`
4. Note any drift in a new version artifact (`hos-cron.v1.md`)
