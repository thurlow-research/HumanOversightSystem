# Cost & Token-Efficiency Management

HOS runs multiple external agent CLIs (`claude`, `agy`/Gemini, `codex`/OpenAI, Copilot)
across a multi-agent pipeline, driven by autonomous cron loops. Token spend is a real,
recurring operating cost, not an afterthought. Several architectural choices were made
specifically to control it.

This document makes that strategy **explicit and honest about its trade-offs**. Every
mechanism below is paired with what it saves *and* what it risks — none are presented as
free wins. Where a choice was recorded as a deliberate decision, it is cross-linked to
[`DECISIONS.md`](../DECISIONS.md); where a mechanism exists but was *not* logged as a cost
decision, that gap is surfaced rather than papered over with invented rationale.

> Scope note: this doc describes the **current** implementation, not aspirational targets.
> Where a planned change is referenced (e.g. model upgrades in
> [#895](https://github.com/thurlow-research/HumanOversightSystem/issues/895)), it is
> labelled as direction, not current state.

---

## 1. Why token cost is a first-class constraint

The pipeline multiplies cost along three axes simultaneously:

- **Multi-agent** — a single change can pass through an authoring chain (pm-agent →
  architect → technical-design → coder), a panel of internal reviewers, a cross-vendor
  second review, and an outer review panel.
- **Multiple vendors** — Claude, Gemini (`agy`), OpenAI (`codex`), and Copilot each draw
  on their own (subscription) budget.
- **Autonomous cron loops** — `bin/hos-cron` fires the worker and overseer on a schedule,
  unattended.

Multi-agent × multiple vendors × autonomous loops means cost scales fast. The framework
therefore optimizes for **cost-per-defect-caught**, not raw thoroughness: scrutiny is
spent where the marginal defect is most likely and most expensive, and deliberately
withheld where cheaper signals already suffice.

---

## 2. Move orchestration out of agents and into cron/shell

Deterministic plumbing does not require model judgment, so it does not run inside model
context. The shell layer — `bin/hos-cron` and the scripts under `scripts/` — handles all
of it before any agent is invoked:

- **Sync, auth, identity guard** — `bin/hos-cron` fetches and fast-forwards `main`,
  loads the subscription OAuth token, and enforces the bot identity guard.
- **Work discovery, pre-computed** — `bin/hos-cron`'s `_build_context` queries the GitHub
  REST API for *open bot PRs* and *next work candidates* (open `needs-ai`, not
  `needs-human`, in the current milestone) and injects them into the prompt as a
  "Pre-computed cycle context" block. The agent reads that block instead of spending
  tokens discovering work itself.
- **PR pre-filtering** — for the overseer, the shell checks each PR's `mergeable_state`
  via REST and passes only actionable PRs onward, so the model never reasons about PRs it
  cannot act on.
- **Idle backoff** — when a cycle finds no work, the launcher backs off (default 1800s)
  rather than re-invoking the model. This idle-backoff suppression is load-bearing for
  cron cost control (see `DECISIONS.md`, the 2026-06-21 cron entry, and #628).

**Rationale:** an agent is invoked only with the minimal boilerplate it needs; discovery,
sync, auth, and filtering are completed deterministically so model attention goes to
routing and judgment, not infrastructure.

**Trade-off:** the shell can skip invocation when there is *provably* no work (no open
PRs/issues, or all PRs await human merge), but it cannot pre-decide cases that *require*
judgment — e.g. whether a task needs human escalation. Those still cost a model call.
The honest claim is "minimal boilerplate per invocation," not "agents never run on empty."

Related decision: [`DECISIONS.md` D5](../DECISIONS.md) (subscriptions, not metered API —
the panel runs locally on prepaid quota rather than double-paying per-call API).

---

## 3. Bounded, curated context per agent

Agents receive scoped inputs rather than whole-repo dumps. Three distinct mechanisms:

- **Diff-centric review (SPEC-379).** Cross-vendor reviewers in `scripts/run_panel.sh` and
  `scripts/run_second_review.sh` receive **only the PR diff** (capped, chunked by file if
  it exceeds the cap), never the full file tree. This is grounded in evidence that
  more-than-diff context *reduces* detection rates, so it improves signal *and* bounds
  tokens at the same time. Requests from a reviewer for "full repo / entire codebase"
  context are logged as advisory and refused.
- **Internal-finding isolation — `panel-context.md` vs `handoff.md`.** The
  oversight-orchestrator writes two outputs: `panel-context.md` (structural risk signals
  only — validated tier, composite score, high-risk areas, spec sections to verify) and
  `handoff.md` (the full picture for the human/PR body, including internal reviewer
  findings). `run_panel.sh` loads **only** `panel-context.md` and explicitly refuses to
  fall back to `handoff.md`.
- **Domain-scoped inner-loop reviewers.** `post-change-sweep` routes each internal
  reviewer to only its domain's changed files (ui/a11y reviewers get changed templates;
  infra-reviewer gets changed infra files; security-reviewer gets changed `.py` plus
  security-relevant context). `scripts/oversight/change_classifier.py` re-derives the
  touched domains deterministically to police this.

**Important honesty note:** the `panel-context.md` / `handoff.md` split is **primarily an
independence (anti-anchoring) invariant**, not a token optimization — if the panel could
read the internal team's conclusions it would converge on them instead of producing an
independent signal. Reduced context is a *side effect* that also saves tokens. Likewise,
domain scoping applies to the **inner-loop** reviewers; the **cross-vendor panel** is
diff-centric, *not* domain-filtered. Do not describe the panel as receiving
CODEOWNERS-routed domain slices — it does not.

**Trade-off:** less context can miss cross-cutting issues. This is mitigated by (a) the
multi-agent split so different agents see different slices, (b) giving security-reviewer
extra context precisely because security defects often live outside the diff, and (c) the
cross-vendor panel as an independent backstop.

Related decisions: [`DECISIONS.md` D22](../DECISIONS.md) (panel/handoff split —
independence invariant enforced in code), D15 (panel diff handling).

---

## 4. Model tiering by stakes

Most agents run on **Sonnet 4.6**; only the highest-judgment authoring agents run on
**Opus 4.8**.

| Tier | Agents |
|---|---|
| **Opus 4.8** | `architect`, `technical-design` (system-level design authority) — and *only* these two |
| **Sonnet 4.6** | every other agent — all reviewers, the oversight layer (`overseer`, `oversight-orchestrator`, `oversight-evaluator`, `risk-assessor`), `pm-agent`, `coder`, `worker`, tests |

The governing principle (`DECISIONS.md` D4): **the AI that authors does not review its own
output.** Opus authors design; Sonnet acts as arbiter/synthesizer (and is explicitly *not*
counted as an independent cross-vendor check); cheaper tiers handle confirmatory triage.

**Current vs. direction:** `pm-agent` and `overseer` currently run on Sonnet 4.6.
[#895](https://github.com/thurlow-research/HumanOversightSystem/issues/895) proposes moving
the design agent (`pm-agent`) and the overseer merge gate to Opus 4.8 — that is a pending
proposal, not the current state. This doc describes the current split: only `architect`
and `technical-design` on Opus, every other agent on Sonnet.

**Cross-vendor decorrelation.** Later stages are covered by *different vendors* rather than
a higher same-vendor tier: `agy` (Gemini) fires at MEDIUM+ and `codex` (OpenAI) at HIGH+
in both the pre-PR second review (`scripts/run_second_review.sh`) and the outer panel
(`scripts/run_panel.sh`). Because the independent check comes from a different training
distribution, the inner-loop same-vendor tier can stay lower without losing the
independence guarantee.

**Trade-off:** capability vs. cost. A Sonnet reviewer may miss something an Opus reviewer
would catch; the bet is that cross-vendor decorrelation and the deterministic floor catch
more, per token, than uniformly upgrading every agent to Opus would. This bet is
empirically testable via the escaped-defect rate.

Related decisions: [`DECISIONS.md` D4](../DECISIONS.md), D15, D16.

---

## 5. Risk-stratified effort allocation

Review effort is allocated by risk tier — the Cleanroom/SQC principle from the README and
METHODOLOGY, restated through the cost lens. From
[`METHODOLOGY.md`](../METHODOLOGY.md) (tier table):

| Tier | Review effort |
|---|---|
| **LOW** | Automated CI gates + Copilot baseline + statistical **spot-check** audit (salted-random SQC sample) |
| **MEDIUM** | + prompt artifact; local panel runs ≥1 cross-vendor reviewer (`agy`); human reviews flagged items |
| **HIGH** | + security lens + **adversary/red-team always-on**; human reviews **line-by-line** |
| **CRITICAL** | HIGH roster + blast-radius required + **mandatory human approval** before merge |

Expensive review (line-by-line human attention, always-on security, red-team) is reserved
for HIGH/CRITICAL. LOW changes get cheap deterministic coverage plus a *sample* of
adversarial review rather than exhaustive review of every change.

**Trade-off:** sampling LOW/MEDIUM means some mis-triaged defects can slip the auto-pass
lane. This is deliberately instrumented: the salted-random red-team sample produces the
**escaped-defect rate**, the primary feedback signal for whether tier thresholds are
calibrated. Pilot rates are elevated (so the sampler visibly fires); production targets are
LOW 5% / MEDIUM 15%.

Related decisions: [`DECISIONS.md` D17](../DECISIONS.md) (SQC random audit), D18 (red-team
always-on at HIGH+).

---

## 6. Deterministic validators before model review

Twelve Python validators (`scripts/oversight/run_validators.sh`) each produce one scored
risk dimension. They are **deterministic** — AST parsing, complexity metrics, git history
queries, migration classification, IP/license scanning, diff size — with **no model
calls** — and they run *first*, before any expensive reviewer. The composite they produce
routes the model attention that follows.

This is the "cheap and deterministic first" principle ([`DECISIONS.md` D7](../DECISIONS.md)):
*never spend an expensive reviewer on something a linter would reject.* Blocking gates
(lint, type-check, secret scan, Bandit HIGH) reject deterministically before the composite
is even computed; model review is spent only on what survives and what the cheap signals
flag.

**Trade-off:** heuristics have false positives and false negatives. A misconfigured
validator degrades coverage rather than zeroing the score (validators that error are
excluded from the weighted average, not counted as 0.0), so a broken tool fails *visible*
rather than silently suppressing signal. The validator set itself is tuned over time
against the escaped-defect signal, and is extensible (#80).

Related decisions: [`DECISIONS.md` D7](../DECISIONS.md), D33 (deterministic re-derivation
of loosening determinations), D52 (deterministic gate findings cannot be suppressed by an
LLM arbiter).

---

## 7. Fail-closed without re-running the model

Where the pipeline cannot get a trustworthy signal, it fails closed **deterministically**
rather than escalating to more model calls. In `scripts/oversight/run_validators.sh`:

- No files provided → write a durable `CRITICAL` summary (fail-closed).
- A required validator fails → composite set to `CRITICAL` (fail-closed).
- All validators fail / no usable output → `composite = 1.0`, `tier = CRITICAL`, with an
  explicit error string, rather than defaulting to `LOW` (which would silently pass broken
  code).

The cost dimension: a failure routes to a human or a deterministic CRITICAL, not to a
retry storm of expensive reviewers. Missing artifacts are treated as hard compliance fails
([`DECISIONS.md` D40](../DECISIONS.md)) instead of being patched by re-invoking the model.

**Trade-off:** fail-closed can surface false CRITICALs (e.g. a validator harness bug). The
run script specifically detects the input shape that would otherwise produce a *false*
CRITICAL and re-splits before defaulting. The accepted residual risk is occasional
over-escalation — paid in human attention, not runaway model spend.

---

## 8. Token tracking & accountability

`scripts/oversight/token_tracker.py` records external-CLI token usage across a build,
appending one record per CLI invocation to `.claudetmp/oversight/token-usage.jsonl`.

- **What it measures:** per-vendor, per-stage, per-step token usage. It uses actual token
  counts from CLI JSON output when available, otherwise estimates at ≈4 chars/token.
- **Subscription awareness:** it compares usage against known monthly quotas and reports a
  *subscription-impact percentage* — `agy` (Gemini) and `codex` (OpenAI) against their
  reserve tiers; `claude` is tracked for awareness only (covered by the subscription).
- **How to read it:**
  ```bash
  # record an event (called from the review shell scripts)
  python3 scripts/oversight/token_tracker.py record --vendor agy --stage second-review \
    --step 3 --prompt-chars 12400 --output-chars 3200
  # today's report
  python3 scripts/oversight/token_tracker.py report
  # all-time report
  python3 scripts/oversight/token_tracker.py report --all
  ```
  The report breaks down totals by vendor and by pipeline stage, with subscription-impact
  warnings.

It also distinguishes **review-event** records (approved / changes-requested / timeout /
skipped) from token-count records, and excludes review events from token totals so human
review outcomes are not conflated with LLM spend.

> **Honest gap:** `token_tracker.py` is implemented and used, but there is **no
> `DECISIONS.md` entry** that records *why* it exists, what budget thresholds it should
> enforce, or whether it should drive automated alerts. The tooling exists ahead of a
> logged decision. This gap is called out here rather than back-filled with invented
> rationale — closing it (a decision entry defining budgets and alerting) is future work.

---

## 9. Trade-offs ledger

| Decision | What it saves | What it risks | Mitigation |
|---|---|---|---|
| Orchestration in shell, not model (§2) | Tokens on discovery/sync/auth/polling | Shell can't pre-decide judgment cases | Skip only on *provably* empty cycles; idle backoff |
| Diff-centric / scoped context (§3) | Tokens per reviewer; better signal | Misses cross-cutting issues | Multi-agent split; security gets extra context; cross-vendor panel |
| Sonnet default, Opus only for design (§4) | Per-token cost across 28 agents | A weaker reviewer misses a defect | Cross-vendor decorrelation; deterministic floor; escaped-defect tracking |
| Risk-stratified effort (§5) | Exhaustive review on LOW/MEDIUM | Mis-triaged defect slips auto-pass | SQC random red-team sample → escaped-defect rate |
| Deterministic validators first (§6) | Expensive review on lint-rejectable code | Heuristic false +/− | Graceful degradation; tuning vs. escaped-defect signal |
| Fail-closed, no retry (§7) | Retry storms of model calls | Occasional false CRITICAL | False-CRITICAL shape detection; human absorbs over-escalation |
| Subscription CLIs, not metered API (D5) | Double-paying per-call API | Local quota exhaustion | token_tracker subscription-impact reporting |

---

## 10. What we deliberately did *not* do

- **Did not drop cross-vendor review to save tokens.** Same-vendor review correlates
  errors; the independent vote *must* come from a different training distribution. The
  extra `agy`/`codex` spend buys decorrelation that a cheaper same-vendor tier cannot
  ([`DECISIONS.md` D4](../DECISIONS.md)).
- **Did not collapse the reviewer panel into one agent.** Independent reviewers seeing
  different slices is the mechanism; one merged agent would re-correlate the findings the
  panel exists to decorrelate.
- **Did not run the panel on metered API.** It runs locally on prepaid subscription quota
  rather than double-paying per-call ([`DECISIONS.md` D5](../DECISIONS.md)).
- **Did not pay full re-validation on every release.** Self-validation is release-scoped:
  full corpus for MAJOR, incremental (`--changed-only`) for MINOR/PATCH — full re-validation
  cost is spent only where blast radius is largest ([`DECISIONS.md` D39](../DECISIONS.md)).
- **Did not let an LLM suppress a cheap deterministic finding** to look clean. Deterministic
  gate findings reach the human verbatim ([`DECISIONS.md` D52](../DECISIONS.md)).

---

## Cross-references

- [`METHODOLOGY.md`](../METHODOLOGY.md) — risk tiers, the twelve signal dimensions, the
  full pipeline.
- [`DECISIONS.md`](../DECISIONS.md) — the recorded decisions cited above (D4, D5, D7, D15,
  D16, D17, D18, D22, D33, D39, D40, D52).
- Model-selection direction:
  [#895](https://github.com/thurlow-research/HumanOversightSystem/issues/895) (proposed
  Opus 4.8 for design agents + overseer merge gate).
- Validator suite: [`scripts/oversight/run_validators.sh`](../scripts/oversight/run_validators.sh).
- Token tracker: [`scripts/oversight/token_tracker.py`](../scripts/oversight/token_tracker.py).
