# Session: A Pipeline That Kept Busy While It Was Stalled, and Redesigning How It Calls for Help

**Date:** 2026-10-15 and 2026-10-20 (two human-proxy sessions; the second continued across a context compaction and a service restart)
**Role:** human-proxy orchestrator (AI session, Human GitHub App identity), working with Scott
**Duration:** several hours across both days (approximate; not logged at session start)
**Artifacts:** issues #2100–#2102, #2119, #2122–#2137 filed or amended; tracker #2119; plan file (outside the repo) with decisions D-1 to D-8; three new findings and five evidence additions in `research/findings/` (this PR)

---

## What this session was

It started with a plain question: "There have been no PRs all day. The worker must be stuck." The answer was stranger. The worker was not stuck. It was busy merging design documents while no code could land, and the human had no way of knowing.

## What was found

1. **`security_scan` was red on every code PR, and the red had nothing to do with any diff.** `pip-audit` audits the shared tool venv. New upstream advisories against `black`, `mcp` and an old `pyjwt` floor failed the gate for every change. Code PRs could not pass readiness.
2. **The worker substituted work instead of stopping.** From 2026-10-14 to 2026-10-20, 13 PRs merged; 12 were requirements, ADR, technical-design or governance-text documents. About 45 built code branches across 36 issues sat unpushed. Each design stage ended in architect escalations, so the human's queue grew while code output was zero. → `findings/a-blocked-gate-redirects-autonomous-work-instead-of-stopping-it.md`
3. **The fix for the gate stalled on an authorization file.** The evaluator required the human to hand-write `step{N}-human-authorization.md` in the worker's clone. The human's interface is GitHub; they do not write files. The issue was filed as #2101 (GitHub-native authorization with a deterministic verifier).
4. **The escalation channel had saturated.** `needs-human` was used both for questions and for parking. It passed 100 items, notified nobody, and hid a 9-day idle worker (2026-10-15). → `findings/an-escalation-channel-shared-with-parking-loses-its-meaning.md`
5. **Background failures.** The Worker's disk temp dir was refused and silently fell back to `/tmp` on every cycle for five days (#2100). The `/tmp` tmpfs quota was exhausted by leaked pytest directories (EDQUOT stopped all shell commands). A Claude Code auto-update removed a CLI flag and crash-looped the human-proxy's own service, invisibly from inside it (#2136).

## Key decisions and why

- **Core-first strategy (#2119).** The human parked all non-core work (24 issues) so that the worker's selection could only reach the issues unblocking the pipeline. The cost was knowingly abusing `needs-human` as a parking label until a real one existed. That cost itself became a finding and issue #2124.
- **Option M for #1776.** Time-boxed, visible exemptions with justifications and tracking issues, all expiring 2027-01-31, instead of disabling the scan. The structural fix is to move `pip-audit` to a scheduled check (#1605).
- **D-5, the "horked environment" rule.** Environment-scoped checks run on a schedule. A new finding, or a check that cannot run, **pauses the pipeline and alerts**; warn-and-skip is forbidden. Later applied to the temp-dir resolver: refusal is fail-closed for cron roles (#2100 amendment).
- **D-2, a direct push channel.** A narrow, deduplicated Pushover "help" path from the cron cycle (#2125), with no dependency on the monitoring stack. The human weighed the irony of depending on a third party for critical alerts and accepted it for now.
- **D-7 re-review policy** for re-adopted stalled branches: a full re-review when merging from main touched a reviewed file or added commits; otherwise evaluator plus delta second review.
- **Release protection for downstream projects.** A consumer install and upgrade smoke test (#2137) becomes a v0.7.0 release gate, because fail-closed temp-dir handling would otherwise stop a consumer's cron on its first post-upgrade cycle.

## Surprises

- **The human-proxy made three process errors, each caught by verification or by the human.**
  - It relayed a worker request that the human hand-write an authorization file. The human's correction: "I don't write authorization files. Directly editing repo is the job of HOS. The human interfaces via git."
  - It quoted a paste-ready ruling in a relay comment, which the human mistook for their own post. → `findings/a-proxys-draft-of-the-humans-ruling-is-mistaken-for-the-humans-act.md`
  - It advised pruning worktrees its sandbox could not see. Git refused, so nothing was lost. Evidence added to `findings/a-gate-must-not-confuse-unreadable-with-unsafe.md`.
- **Each standing working rule the proxy adopted lived only in its private memory.** The human ruled that every such rule must become an issue for the permanent instructions (#2102 scope widened).
- **A sandbox permission rule written with a single leading slash resolves relative to the project.** The proxy's own read/write rules had silently pointed at doubled paths, which left placeholder files in the clone that blocked repo sync (#2134).

## Learnings about the methodology

- **Health metrics must count what is not moving.** "PRs merged" and "issue selected" were both healthy throughout a total code stall. Parked branches, blocked hours and escalations by root cause are the signals that would have shown it (planned for v0.7.1).
- **Recording, disclosing and summoning are three different properties of an escalation.** The system had the first two and lacked the third.
- **The human-proxy is itself an oversight risk surface.** Its drafts can be confused with the human's acts, its filtered view of the filesystem can be confused with the truth, and its working rules can stay unreviewed. All three failures were caught by verification, not by design.

## Artifacts produced

Issues: #2100 (temp dir; ESC rulings and fail-closed amendment by the human), #2101 (GitHub-native authorization; rulings by the human), #2102 (needs-human digest; widened to the proxy's permanent rules), #2119 (core-first tracker), #2122–#2133 (plan spawn), #2134 (sandbox config template), #2135 and #2136 (remote-control service docs and auto-update robustness), #2137 (consumer upgrade release gate). Merged during the session: PR #2121 (#1776 exemptions, `4d5b8cff5`). Plan and handoff files live outside the repo in the human-proxy's handoff directory.
