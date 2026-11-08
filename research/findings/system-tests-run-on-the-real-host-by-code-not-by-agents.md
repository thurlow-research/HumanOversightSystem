# Finding: System Tests Are Their Own Category — They Run on the Real Host, Executed by Code, Confirmed Independently

**Role:** oversight-mechanism. A test tier that CI can run is blind to behaviour that depends on the real environment. Covering that behaviour needs a separate **system test** category: tests that run on the real host against real state, are **executed by deterministic code at fixed pipeline points** (never at an agent's discretion), and are **re-executed by an independent role** to confirm. The LLM interprets results; it never decides whether a test ran or passed.

**First observed:** 2026-11-08, as the design response to the PR #2268 / #2229 miss (see `real-data-not-reviewer-diversity-caught-the-bug.md`). Built as #2289 (v0.7.4, a slice of #2127).

---

## The Finding

HOS's test suite had exactly two special categories, `slow` and `integration`, both release-only, and both runnable anywhere with network access. Nothing represented a test that **needs this host's real state**: the live `/usage` capture the usage-pause poller writes every five minutes, each role's real sandbox profile, the node_exporter textfile directory, cron.

So:
- **The decisive check had no home.** The check that would have caught #2268 ("does the parser accept the real capture?") was not a unit test, because GitHub's runners have no capture. It was not an integration test either, because it needs no network. It existed only as a review-thread request to a human, and nobody ran it.
- **The same gap appears for v0.7.4's own changes.** Per-role sandbox canaries, the metrics bridge and regenerated sandbox policies are all unverifiable in CI.

The gap is a **missing category**, not missing tests. A category is what lets a pipeline require, schedule, record and confirm a test. Without it, an environment-dependent check can only be requested in prose, and prose requests go unexecuted (`unenforceable-rules-need-verification-mechanisms.md`).

## The design that follows (#2289)

1. **Freeze what can be frozen.** A real capture, committed and sanitized as a fixture, turns the *known* real layout into an ordinary CI unit test. This is the cheapest layer, and it alone would have caught #2229 once the new layout appeared.
2. **A `system` category for what cannot be frozen.** These are the live current capture, sandbox profiles and host paths. In CI they report as *skipped with a stated reason*, with the count printed, so they are never silently absent.
3. **Code executes them, not agents.** A runner is invoked at fixed points by pipeline code: the worker's pre-PR step and the overseer's pre-verdict step. A committed path-to-test map selects the tests. It writes a machine-readable evidence record: head SHA, host, per-test results.
4. **Absence is detected in code.** A gate bounces a PR whose mapped `system` evidence is missing, stale or incomplete.
5. **An independent re-execution confirms.** The overseer re-runs the same tests at the PR head and a deterministic comparison flags disagreement. The worker's record alone is never sufficient (`attestation-displaces-the-execution-it-attests-to.md`).
6. **The LLM works after the run.** It interprets failures, writes the bounce text, files bugs through the canonical scripts and proposes fixes. It never decides pass/fail or whether the test ran.

## Why it generalizes

Any agentic pipeline whose software reads real external state (CLI output, API payloads, host configuration, scheduler state, sandbox policy) has this gap. CI-runnable tiers are, by construction, the ones that do not depend on the host. The most environment-sensitive behaviour is therefore exactly the behaviour CI cannot see, and an agent asked to "verify it" in prose will usually not. The three-part remedy is portable:
- a **category** (so it can be required);
- **deterministic execution** (so it always runs);
- **independent re-execution** (so a claim of running is not mistaken for running).

## Implications for research

1. **Test taxonomy is an oversight surface.** Which categories exist decides which checks a pipeline can require. A check with no category is optional by construction. Candidate observation: **O3, "the cheap independent check gets skipped unless forced"**. The category is how a check gets forced.
2. **"Where does it run?" belongs beside "what does it test?"** Diff-scoped, environment-scoped and external-input-scoped checks need different execution sites. That is the subject of #2127 / #2132's scope taxonomy, of which this is the first built slice.
3. **This is deterministic orchestration again.** Code owns *whether, when and what*; the model owns *what it means* (`llms-belong-inside-deterministic-orchestration.md`).

## Terminology note

The base team's `system-test` agent uses "system test" for end-to-end tests derived from the spec. Here "system test" means **runs on the real host against real state**. #2289 requires scoping or renaming one of the two, so the senses do not collide.

## Related findings

- `real-data-not-reviewer-diversity-caught-the-bug.md`: the incident this responds to
- `attestation-displaces-the-execution-it-attests-to.md`: why the overseer re-executes rather than trusting the record
- `llms-belong-inside-deterministic-orchestration.md`: the control split
- `unenforceable-rules-need-verification-mechanisms.md`: a prose request with no checkable artifact is advisory
- `ci-is-blind-to-consumer-environment-failures.md`: the consumer-side sibling of the same blindness
