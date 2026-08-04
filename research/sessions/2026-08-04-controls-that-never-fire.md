# Session: Controls That Exist, Pass Their Tests, and Never Fire

**Date:** 2026-08-03 / 2026-08-04
**Role:** Human-proxy orchestrator (interactive), Human clone
**Duration:** ~11 hours
**Artifacts:** 4 PRs opened — #1235, #1246, #1258 merged, plus this one; 14 issues filed; 4 closed (#1029, #1199, #1230, #1256); ~25 issues commented; 1 milestone created and 4 renumbered; 1 architect ADR commissioned

---

## What this session was

It began as housekeeping — commit a branch-cleanup script — and turned into an audit of
whether this repo's own controls do anything. Six times, the answer was no, and each time the
control was present in prose, present in code, and covered by passing tests.

The session's own working method was the second subject. Two claims were asserted from memory
rather than re-read, one of which corrupted an issue that had been completed thirty minutes
earlier. That failure mode already had a finding written about it, two days prior.

---

## The pattern: a control can be complete and inert

Six independent instances, none of which a reviewer or a test suite would surface:

**1. The security gate never fires (#1253).** `decide_merge_authority()` takes
`security_relevant: bool = False`. It is used once, correctly. `grep` across `scripts/`,
`bin/` and `.claude/` finds **no caller that passes it**. The only caller is the overseer
agent constructing the call from prose in `overseer.md:331-381` — a parameter list that does
not mention it. So the matrix row forcing `HUMAN_REQUIRED` and the hard limit *"never approve
a security-relevant change without human sign-off"* are both unenforced.

Three tests cover the branch. All three pass `security_relevant=True` explicitly. They are
green, and they would remain green forever while production never supplies the input.
**Coverage cannot see a parameter that is never set.**

**2. Missing tools remove dimensions from the risk model (#1266).** `composite_score()`
ignores errored validators (`schema.py:92`). A missing tool therefore does not zero a
dimension — it deletes it from the weighted average, and the tier is reported with no
indication anything is absent. `static_analysis` carries weight 0.15; `bandit` is not
installed in the environment that generates the committed artifacts.

The consumer-facing case is worse. `detect_required_tools()` preflights only *gate* tools —
`tsc`, `astro`, `eslint`. The six `_js` validators depend on `semgrep` and `tree-sitter`,
neither of which is checked. An Astro consumer with eslint installed **passes the preflight
green** while every JS dimension silently vanishes from their risk score. That is v0.6.0's
headline deliverable, inert on a clean install.

The policy that produced it is sound — ADR-032 D2, *"HOS never installs tooling"* — but it
makes detection load-bearing, and detection stopped at the gates. Gates fail visibly.
Validators fail quietly. **The half that fails quietly is the half nobody guarded.**

**3. A closed policy that shipped nothing (#1241).** #314 established *"shell for launch,
Python for logic"* with four acceptance criteria and was closed. Three were never delivered:
`code-reviewer.md` has no such criterion, `METHODOLOGY.md` has no testability principle, and
no validator exists. Both #1167 and #1174 build on it as settled policy.

**4. A promise retired with the thing that would have kept it (#1255).** #888 P5 —
*"retire audit-log sync machinery; commit per-entry records inline"* — removed the sync
machinery. No inline committer was ever added. `audit/log/**` has been write-only since
2026-06, while a `SubagentStop` hook writes a record on every subagent stop in every session.
Then `branch_clean.sh`, merged this same session, deletes them with `git clean -fd`.

The loop closed live: the session's own architect-subagent audit record was destroyed by the
cleanup the session had just shipped. It survived only because it had been quoted verbatim
into the issue beforehand.

**5. Functions that were never written (#1125).** `overseer.md` step 4a instructs the overseer
to call `check_register_completeness`, `record_pr_bounce` and `bounce_count`. None has ever
existed.

**6. A check that fails-closed on every PR, and is therefore ignored (#1170).** §3b compares
the validator artifact against everything merged since its last refresh, rather than against
the PR's own diff. It would route essentially every PR to `HUMAN_REQUIRED` — and the overseer
demonstrably keeps auto-merging. **A gate that fires constantly is a gate that gets routed
around**, which is indistinguishable from a gate that does not exist.

### Why this is a variant, not a repeat

`unenforceable-rules-need-verification-mechanisms.md` (2026-06-11) covers rules an agent
*cannot verify*. This is different and arguably harder to catch: the mechanism **exists, is
correct, and is verifiable** — it simply is never invoked, or is invoked with an input nobody
supplies. Tests pass. Coverage is satisfied. Review sees working code.

The common structure is that **every one of these is a wiring failure, not a logic failure**,
and the artefacts a reviewer inspects — the function, the test, the doc — are each individually
correct. Whether this warrants its own finding is left for @ScottThurlow; none was filed,
consistent with the scope discipline he set mid-session.

---

## Working-method failures

### State assertions were made from memory, twice

**#1204** was read as OPEN at ~17:05 and acted on at 17:35. Scott had merged PR #1234 at
17:08:56, closing it as completed. The result was an overwrite of a finished issue's title and
body with a spec presenting it as open work, plus #1175 and #1192 closed as `not_planned` when
they had in fact been *delivered*. All reverted; corrections posted.

**PR #1258** was reported as awaiting approval after Scott had already merged it. He corrected
it: *"There are no open PRs."*

`state-assertions-decay-faster-than-their-documents.md` was filed 2026-08-02 and describes
exactly this. It recurred twice within 48 hours, in the next Human-proxy session. **The finding
existing did not prevent it** — which is itself the argument that finding makes.

The operational rule that follows: **re-read issue and PR state in the same call that mutates
it.** A `worker-<issue>-…` branch on origin means the issue is being worked and may close at
any moment.

### `needs-ai` was applied without its precondition

The label means *"Human decided; HOS picks it up, **reads `Decision:`**, acts."* It was applied
to #1249 and #1252 with no `Decision:` block present, which would have caused the worker to
find nothing actionable and bounce them straight back. Corrected once Scott flagged the
miscommunication. **A routing label that asserts a decision requires the decision to be
recorded in the form the reader expects.**

### Fourteen issues filed against a backlog being drained

Each investigation surfaced adjacent defects and each was filed. Scott's correction:

> *"Finish what we committed to. 'Critical' only applies to new issues not related to the work
> underway."*

The distinction matters and had been misread: the existing v0.6.0 backlog is **committed
scope** and gets finished, not swept into 0.7.x. The critical-only bar governs *newly
discovered, unrelated* work. An earlier proposal to move 24 of 25 v0.6.0 issues out was
withdrawn unexecuted.

---

## Decisions recorded

| Topic | Decision |
|---|---|
| Shell-logic enforcement (#1167) | Deterministic validator **signal** plus a `code-reviewer` criterion, configurable — explicitly **not** an overseer block. An LLM judging "complex" produces inconsistent verdicts, and 17,233 lines of legitimate bash would be bounced |
| Test regime (#1174, #1242) | Everything **new** must be testable and tested; **existing is grandfathered** on an enumerated, human-gated, monotonically shrinking list. This is the Ratchet Principle applied to coverage — the exempt set may shrink freely and may only grow by explicit human decision |
| #1253 signal source | **Both**, sequenced. `security_surfaces.txt` now, **derived inside** `decide_merge_authority()` rather than passed — a control that depends on a caller remembering an input is how this broke. Static-analysis trigger deferred behind #1266 and #1170 |
| Protected-surface loosening | **Deferred.** Sequenced behind #1205 (cross-vendor review) producing evidence first. Loosening the one demonstrably-working merge control while five others were found broken would have removed the last reliable gate — and loosening on the promise of a future control is the shape of #314 and #888 P5 |
| v0.7.x numbering | **Even numbers are themes; odd are reserved for stabilization/patch.** A new theme takes an even slot, which may force a renumber |

---

## A note on calibration

Scott's observation that protected-surface approvals are *"robo approved"* is the sharpest
governance point of the session. In this repo the protected list covers most of the product,
so the gate fires on nearly every PR and human approval degrades into rubber-stamping.

Meanwhile `fail_under` moved **80 → 79 → 78** across PR #1247 and PR #1262, in a single day.

An earlier draft of this log asserted those merged without human approval. **That was wrong**,
and the error is worth recording because it is the same failure this session kept finding: a
claim about state, made from memory, that a single query would have falsified. Both PRs carry
`ScottThurlow APPROVED` and were merged by him. The Ratchet Principle was satisfied
procedurally.

The observation that survives the correction is subtler, and more useful. In both cases the
threshold *reduction* rode along inside a PR whose stated purpose was **widening the measured
surface** — a tightening. The loosening was a side effect of a change framed as the opposite,
and nothing in review surfaced it as one. Approval was real; attention to that specific line
was not.

**So path-based gating caught the wrong things in both directions on the same day**: it fired
on dozens of neutral protected-surface edits, consuming the attention that would have caught a
threshold drop it did not fire on at all. The proposed discriminator is the ratchet rather than
the path — tightening or neutral changes take cross-vendor review; loosening changes always take
a human — and #1242's ratchet baseline is what would make a threshold decrease a distinct,
deliberate act rather than a line inside an unrelated diff.

---

## Related

- `research/findings/state-assertions-decay-faster-than-their-documents.md` — recurred twice here
- `research/findings/unenforceable-rules-need-verification-mechanisms.md` — the adjacent, distinct case
- `research/findings/ratchet-principle.md` — applied to the test regime this session
- `research/findings/enforcement-gate-scope-gap.md` — *"the function exists; it simply never ran"*; #1253 is the same shape one level deeper
- Issues: #1241, #1242, #1243, #1244, #1253, #1255, #1265, #1266
