# Finding: A gate must never collapse "I couldn't read the reviewer" into "the reviewer says stop"

**Role:** oversight-mechanism — the cross-vendor review caught a real bug the internal chain missed, and the harness threw it away

**First observed:** 2026-06-13, CondoParkShare real-world HOS test run (HOS#113)

---

## The finding

The transition-gate second review shells out to an independent vendor CLI (`agy`) and parses its output for a verdict. The harness assumed a **one-shot JSON responder**: it told agy "Return JSON only: {…}" and extracted the verdict with a regex requiring a fenced block that starts with `{`. But the installed `agy` is an **agentic CLI** — it returns a narrated transcript ("I will list the files… I will run pytest…") followed by a markdown report (`RISK: HIGH`, `## Tier 1 — Must Fix`, numbered findings). No block started with `{`, so the parser found nothing and set `verdict: error` → **fail-closed every MEDIUM+ step**, with `oversight-evaluator` treating `error` as a COMPLIANCE FAIL.

The damage is sharp because the review *worked*: in this very run agy caught a genuine correctness bug the entire internal Claude chain missed and security-review got backwards — `.order_by("-elapsed_hours")` ranks `NULL` (zero-listing) users **first** under Postgres `DESC`. The cross-vendor independent review — the thing the whole methodology exists to provide — produced exactly the signal it was supposed to, and the harness **deleted it** over an output-format assumption.

Two compounding bugs rode along: agy ran *tools* during the review (background pytest, *created* a test file, then reverted it) — a review step mutating the working tree it is reviewing — and the harness **conflated** "I could not parse the reviewer" with "the reviewer judged the code unsafe," the two failure modes a gate must never merge.

## Why it matters for scalable oversight

A gate that consumes a model's output has to be built for what models *actually emit*, not the convenient schema you asked for. A non-deterministic agent will, some fraction of the time, narrate, wrap, reformat, or prose its answer — and if the gate's only two outcomes are "valid JSON → trust it" and "anything else → error," then every such case is a fail-closed that discards a real judgment. Over time that trains operators to distrust and bypass the gate ("it errors all the time"), which is the worst outcome for an oversight control.

The deeper rule is about **states, not parsing**. A reviewing gate has *four* distinct outcomes, and merging any of them is a bug:
- **approve** — reviewer ran, found nothing blocking.
- **request_changes** — reviewer ran, flagged blocking issues.
- **unparseable** — reviewer ran and produced a real review the harness could not auto-structure. The content exists; a human must read it. This is **not** a pass and **not** a crash.
- **error** — reviewer genuinely produced nothing (crash, empty, timeout). Fail-closed.

Collapsing `unparseable` into `error` throws away real reviews (the #113 bug). Collapsing it into `approve` silently passes unread reviews. The state has to exist on its own and route to a human.

## The mechanism (the fix)

- **Read-only reviewer.** Invoke `agy --sandbox` (terminal restrictions) and instruct it in-prompt to review only the provided diff and run no tools — a review must never write to the working tree (a crash mid-review could leave uncommitted edits or corrupt the diff under review).
- **Parse by reviewer section, tolerate prose.** Split the output by `## <reviewer>` headers; for each, try strict JSON first, then fall back to scanning the markdown report for `RISK:` level / "Must Fix" / "Tier 1" / blocking keywords → `request_changes`; explicit low-risk/approve → `approve`; real-but-ambiguous content → `unparseable`; truly empty → `error`.
- **Four states, distinct downstream.** The script fails closed only on `error`; `unparseable` exits 0 with a loud "a human must read this preserved review" notice; `oversight-evaluator` routes `unparseable` to **CONDITIONAL_PROCEED** (human reads the report before merge), never COMPLIANCE FAIL and never silent pass.

## The trap it avoids

"The reviewer returns JSON" is an assumption about a non-deterministic system stated as a fact. Build the gate on it and the gate inherits a silent data-loss path the day the reviewer narrates instead. And the seductive "safe" default — treat anything unparseable as `error`/fail-closed — *feels* conservative but actively destroys the independent judgment the gate exists to capture, while looking like rigor. Conservative is *preserving the review and showing it to a human*, not deleting it because it didn't match a regex.

## Provenance

Observed 2026-06-13 during the CondoParkShare real-world HOS test: `run_second_review.sh` fail-closed a MEDIUM step whose agy review had caught a real Postgres NULL-sort bug. Fixed: `agy --sandbox` + read-only prompt, section-based prose-tolerant parsing, and a four-state verdict (`approve`/`request_changes`/`unparseable`/`error`) wired through `run_second_review.sh` and `oversight-evaluator.md`. Note: `validate_agents.sh` parses agy successfully (different prompt/usage), so this was specific to the second-review harness. Related: `the-recorder-must-not-be-in-the-recorded-set.md` and `the-gate-must-time-out-its-own-dependencies.md` (sibling agy-integration / self-reference bugs from the same run), `nondeterministic-review-gate-converges-on-zero-new.md` (building gates around non-deterministic reviewers).
